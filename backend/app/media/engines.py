"""The media engine — the ONLY bridge from a media job to the heavy A/V libraries.

Like every AI engine in LexiMind (chat/summaries/ingestion/vision), this is INJECTED and imports the
heavy libraries LAZILY, so `app.media.*` imports with no ffmpeg/whisper/pyannote/scenedetect/opencv
and tests substitute a deterministic `FakeMediaEngine`.

`process(job, document, storage, ocr_cache)` is a generator of events the SERVICE consumes + persists:

    {"type": "classification", "media_kind", "media_category", "category_confidence", "language"}
    {"type": "metadata", "duration_ms", "width", "height", "fps", "sample_rate", "channels",
                         "video_codec", "audio_codec", "container", "bitrate"}
    {"type": "stage",   "stage": str, "progress": int, "latency_ms"?: int}
    {"type": "transcript", "segment_index", "start_ms", "end_ms", "text", "speaker_label"?,
                         "confidence", "no_speech_prob", "language", "words"?}
    {"type": "speaker", "speaker_label", "total_speaking_ms", "turn_count", "confidence"}
    {"type": "turn",    "speaker_label", "start_ms", "end_ms"}
    {"type": "scene",   "scene_index", "start_ms", "end_ms", "score", "representative_frame_index"?,
                         "ocr_text"?}
    {"type": "frame",   "frame_index", "timestamp_ms", "scene_index"?, "width", "height", "hash",
                         "is_keyframe", "extraction", "ext", "bytes", "ocr_text"?, "ocr_confidence"?}
    {"type": "subtitle","subtitle_index", "start_ms", "end_ms", "text", "source", "language"}
    {"type": "final",   "pipeline_version"}

`ocr_cache` is a read accessor `get(page_number, content_hash) -> Optional[dict]` — for frame OCR the
engine uses the frame_index as the page number, reusing the Phase-4 OCR cache so a frame's text is
never re-recognized. Frame OCR itself calls the SHARED backend in `app.ingestion.engines` — the OCR
logic is reused, never duplicated (Step 8).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterator, Optional, Protocol

from app.media.classification import ClassificationSignals, classify
from app.media.models import PIPELINE_VERSION
from app.media.validation import media_kind as _kind


class OcrCache(Protocol):
    def get(self, page_number: int, content_hash: str) -> Optional[Dict[str, Any]]: ...


class MediaEngine(Protocol):
    def process(self, job, document, storage, ocr_cache: OcrCache) -> Iterator[Dict[str, Any]]: ...


# ====================================================================== fake (tests + contract)
class FakeMediaEngine:
    """Deterministic stand-in for the heavy engine.

    Emits classification + metadata, a configurable number of transcript segments across two
    speakers, speaker summaries + conversation turns, and (for video) scenes + frames (honoring the
    OCR cache so caching is exercised) + subtitles — mirroring the production event contract without
    any A/V library. Drives EVERY persistence path so the whole pipeline is testable offline.
    """

    def __init__(self, *, media_kind: str = "video", segments: int = 4, speakers: int = 2,
                 scenes: int = 2, frames_per_scene: int = 1, subtitles: int = 2,
                 duration_ms: int = 60_000, language: str = "en", frame_ocr: bool = True):
        self.media_kind = media_kind
        self.segments = segments
        self.speakers = max(1, speakers)
        self.scenes = scenes if media_kind == "video" else 0
        self.frames_per_scene = frames_per_scene
        self.subtitles = subtitles if media_kind == "video" else 0
        self.duration_ms = duration_ms
        self.language = language
        self.frame_ocr = frame_ocr

    def process(self, job, document, storage, ocr_cache) -> Iterator[Dict[str, Any]]:
        category, conf = classify(ClassificationSignals(
            filename=getattr(document, "filename", "") or getattr(document, "display_name", ""),
            media_kind=self.media_kind, speaker_count=self.speakers,
            has_screen_text=self.frame_ocr and self.media_kind == "video", duration_ms=self.duration_ms))
        yield {"type": "classification", "media_kind": self.media_kind, "media_category": category,
               "category_confidence": conf, "language": self.language}
        yield {"type": "metadata", "duration_ms": self.duration_ms,
               "width": 1280 if self.media_kind == "video" else 0,
               "height": 720 if self.media_kind == "video" else 0,
               "fps": 30.0 if self.media_kind == "video" else None,
               "sample_rate": 16000, "channels": 1,
               "video_codec": "h264" if self.media_kind == "video" else "",
               "audio_codec": "aac", "container": (document.file_type or "mp4"), "bitrate": 128000}

        # --- transcription ---
        yield {"type": "stage", "stage": "transcription", "progress": 30, "latency_ms": 5}
        seg_ms = max(1, self.duration_ms // max(1, self.segments))
        for i in range(self.segments):
            label = f"SPEAKER_{i % self.speakers:02d}"
            yield {"type": "transcript", "segment_index": i, "start_ms": i * seg_ms,
                   "end_ms": (i + 1) * seg_ms,
                   "text": f"This is transcript segment {i} spoken by {label}.",
                   "speaker_label": label, "confidence": 0.9, "no_speech_prob": 0.02,
                   "language": self.language,
                   "words": [[w, i * seg_ms, i * seg_ms + 100, 0.9]
                             for w in f"segment {i}".split()]}

        # --- diarization ---
        yield {"type": "stage", "stage": "diarization", "progress": 45, "latency_ms": 4}
        per = self.segments // self.speakers or 1
        for s in range(self.speakers):
            yield {"type": "speaker", "speaker_label": f"SPEAKER_{s:02d}",
                   "total_speaking_ms": per * seg_ms, "turn_count": per, "confidence": 0.85}
        for i in range(self.segments):
            yield {"type": "turn", "speaker_label": f"SPEAKER_{i % self.speakers:02d}",
                   "start_ms": i * seg_ms, "end_ms": (i + 1) * seg_ms}

        # --- scenes + frames (video only) ---
        frame_index = 0
        if self.media_kind == "video":
            yield {"type": "stage", "stage": "scene_detection", "progress": 65, "latency_ms": 6}
            scene_ms = max(1, self.duration_ms // max(1, self.scenes))
            for sc in range(self.scenes):
                yield {"type": "scene", "scene_index": sc, "start_ms": sc * scene_ms,
                       "end_ms": (sc + 1) * scene_ms, "score": 0.7,
                       "representative_frame_index": frame_index}
                yield {"type": "stage", "stage": "frame_extraction", "progress": 75, "latency_ms": 3}
                for _f in range(self.frames_per_scene):
                    ts = sc * scene_ms
                    ocr_text, ocr_conf = "", None
                    if self.frame_ocr:
                        content_hash = f"{document.id}:frame:{frame_index}"
                        cached = ocr_cache.get(frame_index, content_hash)
                        if cached is not None:
                            ocr_text = cached.get("text", "")
                            ocr_conf = cached.get("confidence")
                            yield {"type": "frame", "frame_index": frame_index, "timestamp_ms": ts,
                                   "scene_index": sc, "width": 1280, "height": 720,
                                   "hash": content_hash, "is_keyframe": True, "extraction": "scene",
                                   "ext": "jpg", "bytes": b"\xff\xd8\xfffake",
                                   "ocr_text": ocr_text, "ocr_confidence": ocr_conf,
                                   "content_hash": content_hash, "cached": True}
                        else:
                            ocr_text = f"Slide {sc}: on-screen text for scene {sc}."
                            ocr_conf = 0.88
                            yield {"type": "frame", "frame_index": frame_index, "timestamp_ms": ts,
                                   "scene_index": sc, "width": 1280, "height": 720,
                                   "hash": content_hash, "is_keyframe": True, "extraction": "scene",
                                   "ext": "jpg", "bytes": b"\xff\xd8\xfffake",
                                   "ocr_text": ocr_text, "ocr_confidence": ocr_conf,
                                   "content_hash": content_hash, "cached": False}
                    else:
                        yield {"type": "frame", "frame_index": frame_index, "timestamp_ms": ts,
                               "scene_index": sc, "width": 1280, "height": 720,
                               "hash": f"frmhash{frame_index}", "is_keyframe": True,
                               "extraction": "scene", "ext": "jpg", "bytes": b"\xff\xd8\xfffake"}
                    frame_index += 1

            # --- subtitles ---
            yield {"type": "stage", "stage": "subtitles", "progress": 85, "latency_ms": 2}
            sub_ms = max(1, self.duration_ms // max(1, self.subtitles))
            for si in range(self.subtitles):
                yield {"type": "subtitle", "subtitle_index": si, "start_ms": si * sub_ms,
                       "end_ms": (si + 1) * sub_ms, "text": f"Subtitle cue {si}.",
                       "source": "embedded", "language": self.language}

        yield {"type": "stage", "stage": "chunking", "progress": 92, "latency_ms": 1}
        yield {"type": "final", "pipeline_version": PIPELINE_VERSION}


# ====================================================================== production (lazy heavy libs)
class PipelineMediaEngine:
    """Production engine: ffmpeg/ffprobe for demux+metadata, faster-whisper for ASR, pyannote for
    diarization, PySceneDetect+OpenCV for scenes/frames, and the SHARED ingestion OCR backend for
    on-screen text. Every import is LAZY and every stage degrades gracefully — a missing library
    logs (via the emitted events) and yields nothing for that stage rather than aborting the job, so
    an audio-only box still transcribes even without OpenCV.

    NOTE: heavy libraries are optional and NOT installed in the test/offline environment. This class
    is the real code path; `FakeMediaEngine` exercises the contract deterministically. The concrete
    per-library calls are intentionally defensive scaffolds matching how `PipelineMultimodalEngine`
    ships PaddleOCR support today.
    """

    def __init__(self, *, whisper_model: str = "base", frame_interval_ms: int = 5000,
                 scene_threshold: float = 27.0, max_frames: int = 400):
        self.whisper_model = whisper_model
        self.frame_interval_ms = frame_interval_ms
        self.scene_threshold = scene_threshold
        self.max_frames = max_frames

    # ------------------------------------------------------------------ orchestration
    def process(self, job, document, storage, ocr_cache) -> Iterator[Dict[str, Any]]:
        path = document.storage_path
        ext = (document.file_type or "").lower()
        kind = _kind(ext)

        meta = self._probe(path)
        speakers_hint = 0
        yield {"type": "classification", "media_kind": kind, "media_category": "unknown",
               "category_confidence": None, "language": meta.get("language", "")}
        yield {"type": "metadata", **meta, "duration_ms": meta.get("duration_ms", 0)}

        # --- speech-to-text ---
        yield {"type": "stage", "stage": "transcription", "progress": 25}
        segments = list(self._transcribe(path, meta))
        for ev in segments:
            yield ev

        # --- diarization ---
        yield {"type": "stage", "stage": "diarization", "progress": 45}
        for ev in self._diarize(path, segments):
            speakers_hint += 1 if ev.get("type") == "speaker" else 0
            yield ev

        if kind == "video":
            # --- scenes ---
            yield {"type": "stage", "stage": "scene_detection", "progress": 60}
            scene_events = list(self._detect_scenes(path, meta))
            for ev in scene_events:
                yield ev
            # --- frames + on-screen OCR ---
            yield {"type": "stage", "stage": "frame_extraction", "progress": 75}
            for ev in self._extract_frames(path, meta, scene_events, document, ocr_cache):
                yield ev
            # --- embedded subtitles ---
            yield {"type": "stage", "stage": "subtitles", "progress": 85}
            for ev in self._extract_subtitles(path):
                yield ev

        yield {"type": "stage", "stage": "chunking", "progress": 92}
        yield {"type": "final", "pipeline_version": PIPELINE_VERSION}

    # ------------------------------------------------------------------ metadata (ffprobe)
    def _probe(self, path: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {"duration_ms": 0, "width": 0, "height": 0, "fps": None,
                                "sample_rate": 0, "channels": 0, "video_codec": "", "audio_codec": "",
                                "container": "", "bitrate": 0, "language": ""}
        try:
            import json
            import subprocess
            out = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
                capture_output=True, text=True, timeout=60)
            data = json.loads(out.stdout or "{}")
            fmt = data.get("format", {})
            meta["duration_ms"] = int(float(fmt.get("duration", 0)) * 1000)
            meta["bitrate"] = int(fmt.get("bit_rate", 0) or 0)
            meta["container"] = (fmt.get("format_name", "") or "").split(",")[0]
            for st in data.get("streams", []):
                if st.get("codec_type") == "video" and not meta["video_codec"]:
                    meta["video_codec"] = st.get("codec_name", "")
                    meta["width"] = int(st.get("width", 0) or 0)
                    meta["height"] = int(st.get("height", 0) or 0)
                    meta["fps"] = _parse_fps(st.get("avg_frame_rate", "0/0"))
                elif st.get("codec_type") == "audio" and not meta["audio_codec"]:
                    meta["audio_codec"] = st.get("codec_name", "")
                    meta["sample_rate"] = int(st.get("sample_rate", 0) or 0)
                    meta["channels"] = int(st.get("channels", 0) or 0)
        except Exception:
            pass
        return meta

    # ------------------------------------------------------------------ ASR (faster-whisper)
    def _transcribe(self, path: str, meta: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            return
        try:
            model = _whisper_singleton(self.whisper_model)
            segments, info = model.transcribe(path, word_timestamps=True, vad_filter=True)
            lang = getattr(info, "language", "") or ""
            for i, seg in enumerate(segments):
                words = [[w.word, int(w.start * 1000), int(w.end * 1000), float(getattr(w, "probability", 0.0))]
                         for w in (getattr(seg, "words", None) or [])]
                yield {"type": "transcript", "segment_index": i,
                       "start_ms": int(seg.start * 1000), "end_ms": int(seg.end * 1000),
                       "text": (seg.text or "").strip(),
                       "confidence": float(getattr(seg, "avg_logprob", 0.0)),
                       "no_speech_prob": float(getattr(seg, "no_speech_prob", 0.0)),
                       "language": lang, "words": words or None}
        except Exception:
            return

    # ------------------------------------------------------------------ diarization (pyannote)
    def _diarize(self, path: str, segments) -> Iterator[Dict[str, Any]]:
        try:
            from pyannote.audio import Pipeline as _Pipeline  # noqa
        except Exception:
            # No diarizer available: fall back to a single speaker over all speech.
            if segments:
                total = sum(s["end_ms"] - s["start_ms"] for s in segments if s.get("type") == "transcript")
                yield {"type": "speaker", "speaker_label": "SPEAKER_00",
                       "total_speaking_ms": total, "turn_count": len(segments), "confidence": None}
            return
        try:
            pipeline = _pyannote_singleton()
            diarization = pipeline(path)
            agg: Dict[str, Dict[str, Any]] = {}
            for turn, _, label in diarization.itertracks(yield_label=True):
                start_ms, end_ms = int(turn.start * 1000), int(turn.end * 1000)
                yield {"type": "turn", "speaker_label": label, "start_ms": start_ms, "end_ms": end_ms}
                a = agg.setdefault(label, {"ms": 0, "turns": 0})
                a["ms"] += end_ms - start_ms
                a["turns"] += 1
            for label, a in sorted(agg.items()):
                yield {"type": "speaker", "speaker_label": label,
                       "total_speaking_ms": a["ms"], "turn_count": a["turns"], "confidence": None}
        except Exception:
            return

    # ------------------------------------------------------------------ scene detection (PySceneDetect)
    def _detect_scenes(self, path: str, meta: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        try:
            from scenedetect import detect, ContentDetector  # noqa
        except Exception:
            return
        try:
            scene_list = detect(path, ContentDetector(threshold=self.scene_threshold))
            for idx, (start, end) in enumerate(scene_list):
                yield {"type": "scene", "scene_index": idx,
                       "start_ms": int(start.get_seconds() * 1000),
                       "end_ms": int(end.get_seconds() * 1000),
                       "score": None, "representative_frame_index": idx}
        except Exception:
            return

    # ------------------------------------------------------------------ frames + OCR (OpenCV + shared OCR)
    def _extract_frames(self, path, meta, scene_events, document, ocr_cache) -> Iterator[Dict[str, Any]]:
        try:
            import cv2  # noqa
        except Exception:
            return
        try:
            cap = cv2.VideoCapture(path)
            fps = meta.get("fps") or cap.get(cv2.CAP_PROP_FPS) or 30.0
            # Prefer scene-boundary frames; else periodic.
            timestamps = [ev["start_ms"] for ev in scene_events] or \
                list(range(0, meta.get("duration_ms", 0), self.frame_interval_ms))
            for frame_index, ts in enumerate(timestamps[: self.max_frames]):
                cap.set(cv2.CAP_PROP_POS_MSEC, ts)
                ok, frame = cap.read()
                if not ok:
                    continue
                ok2, buf = cv2.imencode(".jpg", frame)
                data = buf.tobytes() if ok2 else b""
                h, w = frame.shape[:2]
                ocr_text, ocr_conf, content_hash, cached = self._frame_ocr(document, frame_index, data, ocr_cache)
                yield {"type": "frame", "frame_index": frame_index, "timestamp_ms": ts,
                       "scene_index": frame_index if scene_events else None,
                       "width": int(w), "height": int(h), "hash": content_hash or _hash(data),
                       "is_keyframe": True, "extraction": "scene" if scene_events else "periodic",
                       "ext": "jpg", "bytes": data, "ocr_text": ocr_text, "ocr_confidence": ocr_conf,
                       "content_hash": content_hash, "cached": cached}
            cap.release()
        except Exception:
            return

    def _frame_ocr(self, document, frame_index, data, ocr_cache):
        """Run on-screen OCR through the SHARED ingestion backend, honoring the OCR cache."""
        content_hash = _hash(data)
        cached = ocr_cache.get(frame_index, content_hash)
        if cached is not None:
            return cached.get("text", ""), cached.get("confidence"), content_hash, True
        try:
            from app.ingestion.engines import PipelineMultimodalEngine
            text, conf, _boxes, _lang = PipelineMultimodalEngine()._run_ocr_bytes(data)
            return text, conf, content_hash, False
        except Exception:
            return "", None, content_hash, False

    # ------------------------------------------------------------------ embedded subtitles (ffmpeg)
    def _extract_subtitles(self, path: str) -> Iterator[Dict[str, Any]]:
        try:
            import subprocess
            out = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path, "-map", "0:s:0", "-f", "webvtt", "-"],
                                 capture_output=True, text=True, timeout=120)
            for idx, cue in enumerate(_parse_vtt(out.stdout or "")):
                yield {"type": "subtitle", "subtitle_index": idx, "start_ms": cue["start_ms"],
                       "end_ms": cue["end_ms"], "text": cue["text"], "source": "embedded", "language": ""}
        except Exception:
            return


# ---- singletons + small helpers -------------------------------------------------------------
_WHISPER = None
_PYANNOTE = None


def _whisper_singleton(model_name: str):
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        _WHISPER = WhisperModel(model_name, device="auto", compute_type="int8")
    return _WHISPER


def _pyannote_singleton():
    global _PYANNOTE
    if _PYANNOTE is None:
        import os
        from pyannote.audio import Pipeline
        _PYANNOTE = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=os.environ.get("HF_TOKEN"))
    return _PYANNOTE


def _parse_fps(rate: str) -> float | None:
    try:
        num, den = rate.split("/")
        den_f = float(den)
        return round(float(num) / den_f, 3) if den_f else None
    except Exception:
        return None


def _ts_to_ms(ts: str) -> int:
    """Parse a WebVTT/SRT timestamp 'HH:MM:SS.mmm' (or 'MM:SS.mmm') to milliseconds."""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, (m, s) = "0", parts
        else:
            return 0
        return int(h) * 3600_000 + int(m) * 60_000 + int(float(s) * 1000)
    except Exception:
        return 0


def _parse_vtt(text: str):
    """Minimal WebVTT cue parser (yields {start_ms, end_ms, text}). Dependency-free.

    Splits on blank lines; a cue is a block containing a 'start --> end' line followed by text.
    """
    cues = []
    for block in (text or "").replace("\r\n", "\n").split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        timing = next((ln for ln in lines if "-->" in ln), None)
        if timing is None:
            continue
        try:
            left, right = timing.split("-->")
            start_ms = _ts_to_ms(left)
            end_ms = _ts_to_ms(right.split()[0] if right.split() else right)
        except Exception:
            continue
        body = " ".join(ln for ln in lines if "-->" not in ln and ln.strip().upper() != "WEBVTT").strip()
        if body:
            cues.append({"start_ms": start_ms, "end_ms": end_ms, "text": body})
    return cues


def _hash(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", errors="ignore")
    return hashlib.sha1(data or b"").hexdigest()[:32]
