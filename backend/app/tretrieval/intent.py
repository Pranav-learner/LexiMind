"""Temporal query understanding (Step 3) — detect which temporal retrievers a query should activate.

Extends the Phase-1 / mmretrieval query-analysis idea to TIME. A query may activate several temporal
retrievers at once; a named modality (or a parsed timestamp) boosts its fusion weight and sets the
primary intent. Also parses:
  - explicit timestamps ("at 12:04", "around 1:30:00", "after 45 minutes") → a time filter/anchor,
  - relative-order cues ("after the scheduling discussion", "before the break") → order reasoning hint.

Pure + dependency-light (its own tiny tokenizer) so it never pulls torch/rank_bm25.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

_WORD = re.compile(r"[a-z0-9']+")

# Trigger vocabularies per temporal modality.
_TRIGGERS: Dict[str, List[str]] = {
    "speaker": ["speaker", "who said", "who says", "who asked", "who mentioned", "professor",
                "presenter", "host", "guest", "panelist", "interviewer", "said by", "spoke", "voice"],
    "chapter": ["chapter", "section", "part", "segment of", "portion"],
    "topic": ["topic", "about", "regarding", "concerning", "subject of", "theme", "discuss", "discussion"],
    "event": ["happened", "happen", "event", "when did", "after the", "before the", "then what",
              "occurred", "took place", "next", "followed", "following the"],
    "scene": ["scene", "slide", "on screen", "on-screen", "shown", "displayed", "visual"],
    "frame": ["frame", "screenshot", "image at", "picture at", "still", "thumbnail"],
    "subtitle": ["subtitle", "caption", "closed caption"],
    "timestamp": ["timestamp", "at what time", "when", "time when", "minute", "moment"],
}

# Base fusion weights (transcript is the backbone of temporal media).
BASE_WEIGHTS: Dict[str, float] = {
    "transcript": 1.0, "speaker": 0.85, "chapter": 0.7, "topic": 0.75, "event": 0.8,
    "scene": 0.65, "frame": 0.6, "subtitle": 0.7, "timestamp": 0.9,
}
_INTENT_BOOST = 0.6

# Transcript is always searched; timestamp activates only when a time is present/asked.
_ALWAYS = ("transcript",)

# timestamp patterns: HH:MM:SS, MM:SS, "45 minutes", "1 hour 3 min"
_HMS = re.compile(r"\b(\d{1,2}):([0-5]?\d)(?::([0-5]?\d))?\b")
_MINUTES = re.compile(r"\b(\d{1,3})\s*(?:minutes?|mins?|min)\b")
_HOURS = re.compile(r"\b(\d{1,2})\s*(?:hours?|hrs?|hr)\b")
_ORDER_AFTER = re.compile(r"\b(?:after|following|then|next|subsequent to)\b")
_ORDER_BEFORE = re.compile(r"\b(?:before|prior to|preceding|leading up to)\b")

_STOP = {"the", "a", "an", "of", "in", "on", "is", "what", "how", "does", "do", "this", "that",
         "and", "or", "to", "for", "with", "explain", "show", "me", "find", "are", "did", "was",
         "when", "who", "about", "at", "said", "say", "says", "happened", "after", "before"}


@dataclass
class TimeFilter:
    start_ms: int
    end_ms: int
    anchor_ms: int


@dataclass
class TemporalIntent:
    query: str
    keywords: List[str]
    modalities: Set[str]
    weights: Dict[str, float]
    primary: str
    detected: List[str] = field(default_factory=list)
    time_filter: Optional[TimeFilter] = None
    order: Optional[str] = None                     # "after" | "before" | None
    query_type: str = "transcript"                  # coarse type for the prompt builder


def _tokens(text: str) -> List[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1]


def parse_time(query: str) -> Optional[TimeFilter]:
    """Parse an explicit timestamp/offset from the query into a ±window anchor (ms). None if absent."""
    q = query.lower()
    anchor: Optional[int] = None
    m = _HMS.search(q)
    if m:
        h, mm, ss = m.group(1), m.group(2), m.group(3)
        if ss is not None:
            anchor = (int(h) * 3600 + int(mm) * 60 + int(ss)) * 1000
        else:
            anchor = (int(h) * 60 + int(mm)) * 1000       # MM:SS
    else:
        total = 0
        got = False
        mh = _HOURS.search(q)
        if mh:
            total += int(mh.group(1)) * 3600_000; got = True
        mm2 = _MINUTES.search(q)
        if mm2:
            total += int(mm2.group(1)) * 60_000; got = True
        if got:
            anchor = total
    if anchor is None:
        return None
    window = 60_000  # ±60s around the anchor
    return TimeFilter(start_ms=max(0, anchor - window), end_ms=anchor + window, anchor_ms=anchor)


def analyze(query: str) -> TemporalIntent:
    q = (query or "").lower()
    detected: List[str] = []
    for modality, triggers in _TRIGGERS.items():
        if any(t in q for t in triggers):
            detected.append(modality)

    time_filter = parse_time(query)
    if time_filter is not None and "timestamp" not in detected:
        detected.append("timestamp")

    order = "after" if _ORDER_AFTER.search(q) else ("before" if _ORDER_BEFORE.search(q) else None)
    if order and "event" not in detected:
        detected.append("event")

    modalities: Set[str] = set(_ALWAYS) | set(detected)
    weights = {m: BASE_WEIGHTS.get(m, 0.5) for m in modalities}
    for m in detected:
        weights[m] = round(weights.get(m, 0.5) + _INTENT_BOOST, 3)

    primary = max(detected, key=lambda m: weights[m]) if detected else "transcript"

    # Coarse query type drives the adaptive prompt builder.
    if time_filter is not None:
        query_type = "timestamp"
    elif "speaker" in detected:
        query_type = "speaker"
    elif order or "event" in detected:
        query_type = "timeline"
    elif "chapter" in detected or "topic" in detected:
        query_type = "topic"
    elif "scene" in detected or "frame" in detected:
        query_type = "scene"
    else:
        query_type = "transcript"

    return TemporalIntent(query=query, keywords=_tokens(query), modalities=modalities, weights=weights,
                          primary=primary, detected=detected, time_filter=time_filter, order=order,
                          query_type=query_type)
