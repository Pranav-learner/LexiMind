"""Media classification (Step 3) — pure, dependency-free heuristics.

Assigns an uploaded recording a *category* (lecture / meeting / podcast / tutorial / …) from cheap
signals available at ingest time: filename keywords, media kind, speaker count, and screen-share
hints (frame OCR density). This is deliberately model-free (mirrors the rest of the codebase, where
the heavy engine is the only ML bridge) and fully unit-testable. A future model can replace
`classify()` behind the same signature without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

# keyword → category. First match wins on a filename scan (order = specificity).
_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("lecture", "lecture"),
    ("class", "lecture"),
    ("seminar", "lecture"),
    ("course", "lecture"),
    ("standup", "meeting"),
    ("stand-up", "meeting"),
    ("meeting", "meeting"),
    ("sync", "meeting"),
    ("1on1", "meeting"),
    ("1-1", "meeting"),
    ("retro", "meeting"),
    ("podcast", "podcast"),
    ("episode", "podcast"),
    ("ep.", "podcast"),
    ("tutorial", "tutorial"),
    ("howto", "tutorial"),
    ("how-to", "tutorial"),
    ("walkthrough", "tutorial"),
    ("demo", "tutorial"),
    ("interview", "interview"),
    ("presentation", "presentation"),
    ("keynote", "conference_talk"),
    ("talk", "conference_talk"),
    ("conference", "conference_talk"),
    ("webinar", "webinar"),
    ("screen", "screen_recording"),
    ("screencast", "screen_recording"),
    ("recording", "screen_recording"),
    ("memo", "voice_memo"),
    ("voicmemo", "voice_memo"),
)


@dataclass
class ClassificationSignals:
    filename: str = ""
    media_kind: str = "audio"          # audio | video
    speaker_count: int = 0
    has_screen_text: bool = False       # frames carried lots of OCR text (slides / screen share)
    duration_ms: int = 0


def _keyword_category(filename: str) -> str | None:
    name = (filename or "").lower()
    for needle, category in _KEYWORDS:
        if needle in name:
            return category
    return None


def classify(sig: ClassificationSignals) -> Tuple[str, float]:
    """Return (category, confidence in 0..1).

    Strategy: an explicit filename keyword is the strongest signal (high confidence). Absent that,
    fall back to structural heuristics over kind / speakers / screen text.
    """
    kw = _keyword_category(sig.filename)
    if kw is not None:
        return kw, 0.9

    # Structural fallback.
    if sig.media_kind == "audio":
        if sig.speaker_count >= 3:
            return "podcast", 0.55
        if sig.speaker_count == 2:
            return "interview", 0.5
        if sig.speaker_count <= 1 and 0 < sig.duration_ms <= 3 * 60_000:
            return "voice_memo", 0.5
        return "podcast", 0.4

    # video
    if sig.has_screen_text:
        if sig.speaker_count >= 2:
            return "meeting", 0.5
        return "screen_recording", 0.55
    if sig.speaker_count >= 3:
        return "meeting", 0.5
    if sig.speaker_count == 1:
        return "lecture", 0.45
    return "presentation", 0.4


def category_scores(sig: ClassificationSignals) -> Dict[str, float]:
    """Expose a coarse score map (useful for observability / future ranking). Deterministic."""
    cat, conf = classify(sig)
    return {cat: conf}
