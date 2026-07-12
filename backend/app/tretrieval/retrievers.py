"""The temporal retrievers (Step 4) — every temporal signal behind ONE common interface.

`TemporalRetriever` protocol: `modality` + `retrieve(ctx, k) -> list[TemporalHit]`. Concrete retrievers
all read the canonical stores (Module-1 media rows + Module-3 tintel rows), score lexically (bounded,
deterministic, faiss/torch-free) so the whole framework is testable, and ALWAYS preserve exact
timestamps + speaker/scene provenance on every hit (Step 8).

- `TranscriptRetriever` — transcript segments (the backbone). Boosts by time-anchor overlap.
- `SpeakerRetriever`    — speakers (profile match) → their transcript segments as evidence.
- `ChapterRetriever`    — chapters (title/keywords).
- `TopicRetriever`      — topics (label/keywords).
- `EventRetriever`      — timeline events (title/type) — powers "what happened after …".
- `SceneRetriever`      — scenes (their frame OCR / representative content).
- `FrameRetriever`      — frames (on-screen OCR text).
- `SubtitleRetriever`   — subtitle cues.
- `TimestampRetriever`  — segments/frames overlapping a parsed time anchor (time, not keywords).

Add a retriever = a class with a `modality` + `retrieve` registered in `TEMPORAL_RETRIEVERS`
(plug-and-play, per Step 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from sqlalchemy.orm import Session

from app.tretrieval.intent import TimeFilter
from app.tretrieval.repository import TemporalRepository
from app.tretrieval.schemas import TemporalHit


@dataclass
class TemporalContext:
    db: Session
    workspace_id: str
    owner_id: str
    query: str
    keywords: List[str]
    document_id: Optional[str] = None
    time_filter: Optional[TimeFilter] = None
    repo: Optional[TemporalRepository] = None

    def repository(self) -> TemporalRepository:
        if self.repo is None:
            self.repo = TemporalRepository(self.db)
        return self.repo


class TemporalRetriever(Protocol):
    modality: str
    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]: ...


def _fmt(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{(s % 3600) // 60:02d}:{s % 60:02d}"


def lexical_score(keywords: List[str], fields: List[tuple]) -> float:
    """Weighted keyword-overlap score across (text, weight) fields (same scheme as mmretrieval)."""
    if not keywords:
        return 0.0
    total = 0.0
    for text, weight in fields:
        low = (text or "").lower()
        if not low:
            continue
        for kw in keywords:
            if kw in low:
                total += weight * (1.0 + min(low.count(kw) - 1, 3) * 0.15)
    return total


def _time_overlap_bonus(start_ms: int, end_ms: int, tf: Optional[TimeFilter]) -> float:
    """Extra score when a hit overlaps the query's parsed time window (proximity to the anchor)."""
    if tf is None:
        return 0.0
    if end_ms < tf.start_ms or start_ms > tf.end_ms:
        return 0.0
    # closer to the anchor → larger bonus (0..2)
    mid = (start_ms + end_ms) / 2
    dist = abs(mid - tf.anchor_ms)
    return round(2.0 * max(0.0, 1.0 - dist / 60_000.0), 4)


def _finalize(hits: List[TemporalHit], k: int) -> List[TemporalHit]:
    ranked = sorted([h for h in hits if h.raw_score > 0], key=lambda h: h.raw_score, reverse=True)[:k]
    for i, h in enumerate(ranked, start=1):
        h.rank_in_modality = i
    return ranked


# ------------------------------------------------------------------ transcript
class TranscriptRetriever:
    modality = "transcript"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for s in repo.segments(ctx.workspace_id, ctx.document_id):
            base = lexical_score(ctx.keywords, [(s.text, 1.0)])
            bonus = _time_overlap_bonus(s.start_ms, s.end_ms, ctx.time_filter)
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"seg:{s.id}", modality="transcript", source_type="transcript_segment",
                document_id=s.document_id, content=s.text[:600], title=s.speaker_label or "Transcript",
                start_ms=s.start_ms, end_ms=s.end_ms, speaker_id=s.speaker_id,
                speaker_label=s.speaker_label, asset_id=s.id, raw_score=score, proximity_bonus=bonus,
                confidence=float(s.confidence or 0.0),
                metadata={"timespan": f"{_fmt(s.start_ms)}–{_fmt(s.end_ms)}"}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ speaker
class SpeakerRetriever:
    modality = "speaker"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for sp in repo.speakers(ctx.workspace_id, ctx.document_id):
            kw = " ".join(sp.keywords) if getattr(sp, "keywords", None) else ""
            score = lexical_score(ctx.keywords, [(sp.display_name or "", 1.4), (sp.speaker_label, 1.0), (kw, 0.6)])
            if score <= 0:
                continue
            secs = int(sp.total_speaking_ms) // 1000
            hits.append(TemporalHit(
                key=f"speaker:{sp.id}", modality="speaker", source_type="speaker",
                document_id=sp.document_id,
                content=f"{sp.display_name or sp.speaker_label}: {sp.turn_count} turns, {secs}s speaking.",
                title=sp.display_name or sp.speaker_label, start_ms=0, end_ms=sp.total_speaking_ms,
                speaker_id=sp.id, speaker_label=sp.speaker_label, raw_score=score,
                confidence=float(sp.confidence or 0.0),
                metadata={"turn_count": sp.turn_count, "segment_count": sp.segment_count}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ chapter
class ChapterRetriever:
    modality = "chapter"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for c in repo.chapters(ctx.workspace_id, ctx.document_id):
            kw = " ".join(c.keywords or [])
            base = lexical_score(ctx.keywords, [(c.title, 1.4), (c.summary or "", 1.0), (kw, 0.8)])
            bonus = _time_overlap_bonus(c.start_ms, c.end_ms, ctx.time_filter)
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"chapter:{c.id}", modality="chapter", source_type="chapter", document_id=c.document_id,
                content=(c.summary or c.title)[:600], title=c.title, start_ms=c.start_ms, end_ms=c.end_ms,
                chapter_id=c.id, asset_id=c.id, raw_score=score, proximity_bonus=bonus,
                confidence=float(c.confidence or 0.0),
                metadata={"keywords": c.keywords, "timespan": f"{_fmt(c.start_ms)}–{_fmt(c.end_ms)}",
                          "source": c.source}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ topic
class TopicRetriever:
    modality = "topic"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for t in repo.topics(ctx.workspace_id, ctx.document_id):
            kw = " ".join(t.keywords or [])
            base = lexical_score(ctx.keywords, [(t.label, 1.5), (kw, 0.9)])
            bonus = _time_overlap_bonus(t.start_ms, t.end_ms, ctx.time_filter)
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"topic:{t.id}", modality="topic", source_type="topic", document_id=t.document_id,
                content=f"Topic: {t.label} ({', '.join(t.keywords or [])})", title=t.label,
                start_ms=t.start_ms, end_ms=t.end_ms, topic_id=t.id, asset_id=t.id, raw_score=score,
                proximity_bonus=bonus, confidence=float(t.salience or 0.0),
                metadata={"salience": t.salience, "source": t.source}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ event / timeline
class EventRetriever:
    modality = "event"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for e in repo.events(ctx.workspace_id, ctx.document_id):
            base = lexical_score(ctx.keywords, [(e.title, 1.3), (e.description or "", 1.0),
                                                (e.event_type.replace("_", " "), 0.6)])
            bonus = _time_overlap_bonus(e.start_ms, e.end_ms, ctx.time_filter)
            # events are structurally useful even without keyword match — small floor when time-anchored
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"event:{e.id}", modality="event", source_type="event", document_id=e.document_id,
                content=(e.description or e.title)[:600], title=e.title, start_ms=e.start_ms,
                end_ms=e.end_ms, speaker_id=e.speaker_id, scene_id=e.scene_id, chapter_id=e.chapter_id,
                asset_id=e.id, raw_score=score, proximity_bonus=bonus, confidence=float(e.confidence or 0.0),
                metadata={"event_type": e.event_type, "at": _fmt(e.timestamp_ms), "source": e.source}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ scene
class SceneRetriever:
    modality = "scene"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        # Preload frame OCR per scene so scene content is searchable.
        frames = repo.frames(ctx.workspace_id, ctx.document_id)
        ocr_by_scene: dict = {}
        for f in frames:
            if f.scene_id and (f.ocr_text or "").strip():
                ocr_by_scene.setdefault(f.scene_id, []).append(f.ocr_text)
        hits: List[TemporalHit] = []
        for sc in repo.scenes(ctx.workspace_id, ctx.document_id):
            ocr = " ".join(ocr_by_scene.get(sc.id, []))
            base = lexical_score(ctx.keywords, [(ocr, 1.0)])
            bonus = _time_overlap_bonus(sc.start_ms, sc.end_ms, ctx.time_filter)
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"scene:{sc.id}", modality="scene", source_type="scene", document_id=sc.document_id,
                content=(ocr or f"Scene {sc.scene_index + 1}")[:600], title=f"Scene {sc.scene_index + 1}",
                start_ms=sc.start_ms, end_ms=sc.end_ms, scene_id=sc.id,
                frame_id=sc.representative_frame_id, asset_id=sc.id, raw_score=score, proximity_bonus=bonus,
                metadata={"timespan": f"{_fmt(sc.start_ms)}–{_fmt(sc.end_ms)}"}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ frame (on-screen OCR)
class FrameRetriever:
    modality = "frame"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for f in repo.frames(ctx.workspace_id, ctx.document_id):
            ocr = (f.ocr_text or "").strip()
            base = lexical_score(ctx.keywords, [(ocr, 1.0)])
            bonus = _time_overlap_bonus(f.timestamp_ms, f.timestamp_ms, ctx.time_filter)
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"frame:{f.id}", modality="frame", source_type="frame", document_id=f.document_id,
                content=(ocr or f"Frame at {_fmt(f.timestamp_ms)}")[:600], title=f"Frame {_fmt(f.timestamp_ms)}",
                start_ms=f.timestamp_ms, end_ms=f.timestamp_ms, scene_id=f.scene_id, frame_id=f.id,
                asset_id=f.id, raw_score=score, proximity_bonus=bonus,
                confidence=float(f.ocr_confidence or 0.0), metadata={"at": _fmt(f.timestamp_ms)}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ subtitle
class SubtitleRetriever:
    modality = "subtitle"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for s in repo.subtitles(ctx.workspace_id, ctx.document_id):
            base = lexical_score(ctx.keywords, [(s.text, 1.0)])
            bonus = _time_overlap_bonus(s.start_ms, s.end_ms, ctx.time_filter)
            score = base + bonus
            if score <= 0:
                continue
            hits.append(TemporalHit(
                key=f"sub:{s.id}", modality="subtitle", source_type="subtitle", document_id=s.document_id,
                content=s.text[:600], title="Subtitle", start_ms=s.start_ms, end_ms=s.end_ms,
                asset_id=s.id, raw_score=score, proximity_bonus=bonus,
                metadata={"source": s.source, "timespan": f"{_fmt(s.start_ms)}–{_fmt(s.end_ms)}"}))
        return _finalize(hits, k)


# ------------------------------------------------------------------ timestamp (time, not keywords)
class TimestampRetriever:
    """Pure time retrieval: return the segments/frames overlapping the query's parsed time anchor.
    Activated only when a timestamp is present; scores by proximity to the anchor."""

    modality = "timestamp"

    def retrieve(self, ctx: TemporalContext, k: int) -> List[TemporalHit]:
        tf = ctx.time_filter
        if tf is None:
            return []
        repo = ctx.repository()
        hits: List[TemporalHit] = []
        for s in repo.segments(ctx.workspace_id, ctx.document_id):
            if s.end_ms < tf.start_ms or s.start_ms > tf.end_ms:
                continue
            bonus = _time_overlap_bonus(s.start_ms, s.end_ms, tf)
            score = 1.0 + bonus  # everything in-window is relevant; proximity ranks it
            hits.append(TemporalHit(
                key=f"seg:{s.id}", modality="timestamp", source_type="transcript_segment",
                document_id=s.document_id, content=s.text[:600], title=f"At {_fmt(s.start_ms)}",
                start_ms=s.start_ms, end_ms=s.end_ms, speaker_id=s.speaker_id,
                speaker_label=s.speaker_label, asset_id=s.id, raw_score=score, proximity_bonus=bonus,
                confidence=float(s.confidence or 0.0),
                metadata={"timespan": f"{_fmt(s.start_ms)}–{_fmt(s.end_ms)}", "anchor": _fmt(tf.anchor_ms)}))
        return _finalize(hits, k)


# Registry (plug-and-play; the orchestrator picks the activated subset).
TEMPORAL_RETRIEVERS = {
    "transcript": TranscriptRetriever(), "speaker": SpeakerRetriever(), "chapter": ChapterRetriever(),
    "topic": TopicRetriever(), "event": EventRetriever(), "scene": SceneRetriever(),
    "frame": FrameRetriever(), "subtitle": SubtitleRetriever(), "timestamp": TimestampRetriever(),
}
