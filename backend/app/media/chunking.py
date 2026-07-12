"""Temporal chunk generation (Step 9) — the analogue of `app.ingestion.chunking` for media.

Turns extracted temporal assets (transcript segments, speakers, scenes, subtitles, frame-OCR,
frames) into UNIFIED `MediaChunk` dicts, each carrying a `[start_ms, end_ms)` window so future
timeline-aware retrieval has a temporal anchor. Like the multimodal chunker, chunks are NOT embedded
here (they sit in the future embedding queue) so this is a lightweight, dependency-free builder —
fully unit-testable without ffmpeg/whisper.

Transcript segments are grouped into ~MAX_WORDS windows that NEVER cross a speaker boundary, so a
transcript chunk always has a single attributable speaker. Every other asset maps to one chunk with
a searchable text descriptor (the subtitle text, the scene's frame-OCR, a frame placeholder, …).

Pure functions only (no I/O, no ORM).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

MAX_WORDS = 220           # transcript words per chunk (kept close to the text chunker's 250 budget)
MAX_GAP_MS = 20_000       # split a transcript chunk if there is a >20s silence gap


def _fmt_ts(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _flush_transcript(buf: List[Dict[str, Any]], idx: int, out: List[Dict[str, Any]]) -> int:
    if not buf:
        return idx
    text = " ".join(s.get("text", "").strip() for s in buf if s.get("text", "").strip()).strip()
    if not text:
        return idx
    start_ms = min(int(s.get("start_ms", 0)) for s in buf)
    end_ms = max(int(s.get("end_ms", 0)) for s in buf)
    speaker_label = buf[0].get("speaker_label", "") or ""
    speaker_id = buf[0].get("speaker_id")
    out.append({
        "chunk_type": "transcript", "source": "asr", "chunk_index": idx,
        "start_ms": start_ms, "end_ms": end_ms, "speaker_id": speaker_id, "scene_id": None,
        "asset_id": buf[0].get("id"),
        "content": text,
        "meta": {"speaker_label": speaker_label, "segment_count": len(buf),
                 "timespan": f"{_fmt_ts(start_ms)}–{_fmt_ts(end_ms)}"},
    })
    return idx + 1


def _transcript_chunks(segments: List[Dict[str, Any]], start_idx: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    idx = start_idx
    buf: List[Dict[str, Any]] = []
    words = 0
    prev_end: Optional[int] = None
    prev_speaker: Optional[str] = None
    for seg in sorted(segments, key=lambda s: (int(s.get("start_ms", 0)), int(s.get("segment_index", 0)))):
        sp = seg.get("speaker_label", "") or ""
        gap = (int(seg.get("start_ms", 0)) - prev_end) if prev_end is not None else 0
        boundary = (prev_speaker is not None and sp != prev_speaker) or (gap > MAX_GAP_MS)
        pw = len((seg.get("text", "") or "").split())
        if buf and (boundary or words + pw > MAX_WORDS):
            idx = _flush_transcript(buf, idx, out)
            buf, words = [], 0
        buf.append(seg)
        words += pw
        prev_end = int(seg.get("end_ms", 0))
        prev_speaker = sp
    idx = _flush_transcript(buf, idx, out)
    return out


def build_media_chunks(
    *,
    segments: List[Dict[str, Any]],
    speakers: List[Dict[str, Any]],
    scenes: List[Dict[str, Any]],
    subtitles: List[Dict[str, Any]],
    frames: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Turn extracted temporal assets into unified media-chunk dicts.

    Each returned dict: {chunk_type, source, chunk_index, start_ms, end_ms, speaker_id, scene_id,
    asset_id, content, meta}. `chunk_index` is a global running order. Frame-OCR text becomes `ocr`
    chunks; frames with no OCR become lightweight `frame` placeholder chunks (so a future vision
    module has an anchor). Speaker/scene/subtitle each map to one descriptor chunk.
    """
    out: List[Dict[str, Any]] = []

    # --- transcript chunks (speaker-coherent windows) ---
    out.extend(_transcript_chunks(segments, len(out)))

    # --- speaker chunks (one per speaker: a profile descriptor) ---
    for sp in sorted(speakers, key=lambda s: s.get("speaker_label", "")):
        secs = int(sp.get("total_speaking_ms", 0)) / 1000
        content = (f"Speaker {sp.get('display_name') or sp.get('speaker_label', '')}: "
                   f"{sp.get('turn_count', 0)} turns, {secs:.0f}s speaking.")
        out.append({
            "chunk_type": "speaker", "source": "diarizer", "chunk_index": len(out),
            "start_ms": 0, "end_ms": int(sp.get("total_speaking_ms", 0)),
            "speaker_id": sp.get("id"), "scene_id": None, "asset_id": sp.get("id"),
            "content": content,
            "meta": {"speaker_label": sp.get("speaker_label", ""), "turn_count": sp.get("turn_count", 0)},
        })

    # --- scene chunks ---
    for sc in sorted(scenes, key=lambda s: int(s.get("start_ms", 0))):
        content = sc.get("ocr_text") or f"[Scene {sc.get('scene_index', 0)} " \
                                        f"{_fmt_ts(sc.get('start_ms', 0))}–{_fmt_ts(sc.get('end_ms', 0))}]"
        out.append({
            "chunk_type": "scene", "source": "scenedet", "chunk_index": len(out),
            "start_ms": int(sc.get("start_ms", 0)), "end_ms": int(sc.get("end_ms", 0)),
            "speaker_id": None, "scene_id": sc.get("id"),
            "asset_id": sc.get("representative_frame_id"),
            "content": content,
            "meta": {"scene_index": sc.get("scene_index", 0), "duration_ms": sc.get("duration_ms", 0)},
        })

    # --- subtitle chunks ---
    for sub in sorted(subtitles, key=lambda s: int(s.get("start_ms", 0))):
        text = (sub.get("text", "") or "").strip()
        if not text:
            continue
        out.append({
            "chunk_type": "subtitle", "source": "subtitle", "chunk_index": len(out),
            "start_ms": int(sub.get("start_ms", 0)), "end_ms": int(sub.get("end_ms", 0)),
            "speaker_id": None, "scene_id": None, "asset_id": sub.get("id"),
            "content": text,
            "meta": {"subtitle_source": sub.get("source", "embedded"), "language": sub.get("language", "")},
        })

    # --- frame OCR + frame placeholder chunks ---
    for fr in sorted(frames, key=lambda f: int(f.get("timestamp_ms", 0))):
        ocr = (fr.get("ocr_text", "") or "").strip()
        ts = int(fr.get("timestamp_ms", 0))
        if ocr:
            out.append({
                "chunk_type": "ocr", "source": "ocr", "chunk_index": len(out),
                "start_ms": ts, "end_ms": ts, "speaker_id": None,
                "scene_id": fr.get("scene_id"), "asset_id": fr.get("id"),
                "content": ocr,
                "meta": {"at": _fmt_ts(ts), "confidence": fr.get("ocr_confidence")},
            })
        elif fr.get("is_keyframe"):
            out.append({
                "chunk_type": "frame", "source": "frame", "chunk_index": len(out),
                "start_ms": ts, "end_ms": ts, "speaker_id": None,
                "scene_id": fr.get("scene_id"), "asset_id": fr.get("id"),
                "content": f"[Keyframe at {_fmt_ts(ts)}]",
                "meta": {"at": _fmt_ts(ts), "extraction": fr.get("extraction", "keyframe")},
            })

    return out
