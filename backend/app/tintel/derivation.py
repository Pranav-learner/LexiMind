"""Lightweight derivation of chapters, topics, and timeline events (foundational baseline).

Pure, dependency-free heuristics over Module-1 outputs (transcript segments, speaker turns, scenes).
This is deliberately NOT the full Temporal Intelligence Engine (Module 2): no semantic segmentation,
no LLM chapter titling, no event classification. It produces a reasonable *baseline* population of the
canonical `Chapter`/`Topic`/`TimelineEvent` tables so Module-3 retrieval works end-to-end today; a
later, smarter Module-2 pass ENRICHES the same rows.

Design:
- Chapters = scene-aligned sections (or fixed ~5-minute windows when a recording has no scenes),
  titled by their most salient transcript keywords.
- Topics   = contiguous runs of transcript segments sharing a dominant keyword (a cheap proxy for
  topic segmentation), labelled by that keyword.
- Events   = chapter starts + scene changes + speaker changes (+ topic shifts), ordered by time.

All functions return plain dicts; the repository/service turns them into ORM rows.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "of", "in", "on", "is", "it", "to", "and", "or", "for", "with", "that",
    "this", "was", "are", "be", "as", "at", "by", "we", "you", "i", "so", "but", "if", "then",
    "there", "here", "what", "when", "how", "they", "he", "she", "have", "has", "had", "will",
    "can", "do", "does", "not", "no", "yes", "our", "your", "their", "its", "about", "into",
    "from", "up", "out", "just", "like", "get", "got", "going", "gonna", "okay", "ok", "um", "uh",
    "actually", "really", "kind", "sort", "know", "think", "right", "now", "one", "also", "some",
}
FIXED_WINDOW_MS = 5 * 60_000  # chapter window when no scenes exist


def _tokens(text: str) -> List[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2]


def top_keywords(text: str, n: int = 5) -> List[str]:
    freq: Dict[str, int] = {}
    for w in _tokens(text):
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def _title_from_keywords(keywords: List[str], fallback: str) -> str:
    if not keywords:
        return fallback
    return ", ".join(k.capitalize() for k in keywords[:3])


# --------------------------------------------------------------------- chapters
def derive_chapters(segments: List[Dict[str, Any]], scenes: List[Dict[str, Any]],
                    duration_ms: int) -> List[Dict[str, Any]]:
    """Scene-aligned chapters (fallback: fixed windows). Each dict: index/title/keywords/start/end."""
    segs = sorted(segments, key=lambda s: int(s.get("start_ms", 0)))
    if scenes:
        bounds = [(int(s.get("start_ms", 0)), int(s.get("end_ms", 0))) for s in
                  sorted(scenes, key=lambda s: int(s.get("start_ms", 0)))]
    else:
        total = duration_ms or (max((int(s.get("end_ms", 0)) for s in segs), default=0))
        bounds = [(w, min(total, w + FIXED_WINDOW_MS)) for w in range(0, max(1, total), FIXED_WINDOW_MS)]
        if not bounds:
            bounds = [(0, total)]

    out: List[Dict[str, Any]] = []
    for idx, (start, end) in enumerate(bounds):
        text = " ".join(s.get("text", "") for s in segs if start <= int(s.get("start_ms", 0)) < end)
        kws = top_keywords(text, 5)
        out.append({
            "chapter_index": idx, "title": _title_from_keywords(kws, f"Chapter {idx + 1}"),
            "keywords": kws, "start_ms": start, "end_ms": end,
            "confidence": 0.5 if kws else 0.3,
        })
    return out


# --------------------------------------------------------------------- topics
def derive_topics(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Contiguous runs of segments sharing a dominant keyword → topic segments."""
    segs = sorted(segments, key=lambda s: int(s.get("start_ms", 0)))
    if not segs:
        return []
    runs: List[Dict[str, Any]] = []
    cur_kw = None
    cur: List[Dict[str, Any]] = []
    for seg in segs:
        kws = top_keywords(seg.get("text", ""), 1)
        kw = kws[0] if kws else None
        if kw is not None and kw == cur_kw:
            cur.append(seg)
        else:
            if cur and cur_kw:
                runs.append({"kw": cur_kw, "segs": cur})
            cur_kw, cur = kw, [seg]
    if cur and cur_kw:
        runs.append({"kw": cur_kw, "segs": cur})

    total = sum(len(r["segs"]) for r in runs) or 1
    out: List[Dict[str, Any]] = []
    for idx, run in enumerate(runs):
        rsegs = run["segs"]
        text = " ".join(s.get("text", "") for s in rsegs)
        out.append({
            "topic_index": idx, "label": run["kw"].capitalize(),
            "keywords": top_keywords(text, 6),
            "start_ms": int(rsegs[0].get("start_ms", 0)), "end_ms": int(rsegs[-1].get("end_ms", 0)),
            "salience": round(len(rsegs) / total, 4), "confidence": 0.4,
        })
    return out


# --------------------------------------------------------------------- events
def derive_events(segments: List[Dict[str, Any]], turns: List[Dict[str, Any]],
                  scenes: List[Dict[str, Any]], chapters: List[Dict[str, Any]],
                  topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge chapter-start / scene-change / speaker-change / topic-shift into one ordered timeline."""
    events: List[Dict[str, Any]] = []

    for ch in chapters:
        events.append({"event_type": "chapter_start", "title": ch["title"],
                       "timestamp_ms": int(ch["start_ms"]), "start_ms": int(ch["start_ms"]),
                       "end_ms": int(ch["end_ms"]), "confidence": ch.get("confidence")})

    for sc in sorted(scenes, key=lambda s: int(s.get("start_ms", 0))):
        events.append({"event_type": "scene_change",
                       "title": f"Scene {int(sc.get('scene_index', 0)) + 1}",
                       "timestamp_ms": int(sc.get("start_ms", 0)), "start_ms": int(sc.get("start_ms", 0)),
                       "end_ms": int(sc.get("end_ms", 0)), "scene_id": sc.get("id"), "confidence": 0.6})

    prev = None
    for t in sorted(turns, key=lambda x: int(x.get("start_ms", 0))):
        label = t.get("speaker_label", "")
        if label != prev:
            events.append({"event_type": "speaker_change", "title": f"{label} speaking",
                           "timestamp_ms": int(t.get("start_ms", 0)), "start_ms": int(t.get("start_ms", 0)),
                           "end_ms": int(t.get("end_ms", 0)), "speaker_id": t.get("speaker_id"),
                           "confidence": 0.7})
            prev = label

    for tp in topics[1:]:  # first topic isn't a "shift"
        events.append({"event_type": "topic_shift", "title": f"Topic: {tp['label']}",
                       "timestamp_ms": int(tp["start_ms"]), "start_ms": int(tp["start_ms"]),
                       "end_ms": int(tp["end_ms"]), "confidence": tp.get("confidence")})

    events.sort(key=lambda e: (int(e.get("timestamp_ms", 0)), e.get("event_type", "")))
    for i, e in enumerate(events):
        e["event_index"] = i
    return events
