"""Temporal-intelligence business logic — derive + persist the canonical chapter/topic/event rows.

`ensure_derived` is a transparent, count-guarded freshness check (like `citations.ensure_synced`):
temporal retrieval calls it before searching, so the canonical tables are always populated for a
processed recording without touching Module-1's pipeline. `derive` does an idempotent per-document
delete+rebuild from the lightweight heuristics. Module 2 will later re-run a smarter derivation that
ENRICHES these rows (higher `source`/`confidence`, better titles/summaries).
"""

from __future__ import annotations

from typing import List, Optional

from app.tintel import derivation
from app.tintel.errors import MediaNotFound, NotProcessed
from app.tintel.models import Chapter, TimelineEvent, Topic
from app.tintel.repository import TemporalIntelRepository


class TemporalIntelService:
    def __init__(self, repo: TemporalIntelRepository):
        self.repo = repo
        self.db = repo.db

    # ------------------------------------------------------------------ helpers
    def _document(self, document_id: str, owner_id: str, workspace_id: str):
        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise MediaNotFound(document_id)
        return doc

    # ------------------------------------------------------------------ derivation
    def ensure_derived(self, document_id: str, owner_id: str, workspace_id: str) -> None:
        """Populate the canonical tables if a completed media job has no intelligence yet. Cheap."""
        job = self.repo.latest_job(document_id)
        if job is None or job.status != "completed":
            return  # nothing to derive from; not an error on the retrieval path
        if self.repo.count(document_id) > 0:
            return  # already derived (Module 2 may have enriched it — never clobber)
        self._derive_now(document_id, owner_id, workspace_id, job)

    def derive(self, document_id: str, owner_id: str, workspace_id: str, *, force: bool = False):
        """Explicit (re)derivation endpoint. 409 if media isn't processed."""
        self._document(document_id, owner_id, workspace_id)
        job = self.repo.latest_job(document_id)
        if job is None or job.status != "completed":
            raise NotProcessed(document_id)
        if force or self.repo.count(document_id) == 0:
            self._derive_now(document_id, owner_id, workspace_id, job)
        return self.counts(document_id)

    def _derive_now(self, document_id, owner_id, workspace_id, job) -> None:
        segs = [{"start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text,
                 "speaker_label": s.speaker_label} for s in self.repo.segments(document_id)]
        turns = [{"start_ms": t.start_ms, "end_ms": t.end_ms, "speaker_label": t.speaker_label,
                  "speaker_id": t.speaker_id} for t in self.repo.turns(document_id)]
        scenes = [{"id": sc.id, "scene_index": sc.scene_index, "start_ms": sc.start_ms,
                   "end_ms": sc.end_ms} for sc in self.repo.scenes(document_id)]

        chapters = derivation.derive_chapters(segs, scenes, int(getattr(job, "duration_ms", 0) or 0))
        topics = derivation.derive_topics(segs)
        events = derivation.derive_events(segs, turns, scenes, chapters, topics)

        self.repo.clear(document_id)
        common = dict(workspace_id=workspace_id, owner_id=owner_id, document_id=document_id, job_id=job.id)
        rows: List = []
        chapter_rows = [Chapter(**common, chapter_index=c["chapter_index"], title=c["title"][:300],
                                keywords=c.get("keywords"), start_ms=c["start_ms"], end_ms=c["end_ms"],
                                confidence=c.get("confidence")) for c in chapters]
        rows += chapter_rows
        rows += [Topic(**common, topic_index=t["topic_index"], label=t["label"][:200],
                       keywords=t.get("keywords"), start_ms=t["start_ms"], end_ms=t["end_ms"],
                       salience=t.get("salience"), confidence=t.get("confidence")) for t in topics]
        # Link chapter_start events to their chapter rows by index.
        chap_by_index = {c.chapter_index: c.id for c in chapter_rows}
        cidx = 0
        event_rows = []
        for e in events:
            chapter_id = None
            if e["event_type"] == "chapter_start":
                chapter_id = chap_by_index.get(cidx)
                cidx += 1
            event_rows.append(TimelineEvent(
                **common, event_index=e["event_index"], event_type=e["event_type"], title=e["title"][:300],
                timestamp_ms=e["timestamp_ms"], start_ms=e["start_ms"], end_ms=e["end_ms"],
                speaker_id=e.get("speaker_id"), scene_id=e.get("scene_id"), chapter_id=chapter_id,
                confidence=e.get("confidence")))
        rows += event_rows
        self.repo.add_all(rows)

    # ------------------------------------------------------------------ queries
    def chapters(self, document_id: str, owner_id: str, workspace_id: str, *, ensure: bool = True):
        self._document(document_id, owner_id, workspace_id)
        if ensure:
            self.ensure_derived(document_id, owner_id, workspace_id)
        return self.repo.chapters(document_id)

    def topics(self, document_id: str, owner_id: str, workspace_id: str, *, ensure: bool = True):
        self._document(document_id, owner_id, workspace_id)
        if ensure:
            self.ensure_derived(document_id, owner_id, workspace_id)
        return self.repo.topics(document_id)

    def events(self, document_id: str, owner_id: str, workspace_id: str,
               event_type: Optional[str] = None, *, ensure: bool = True):
        self._document(document_id, owner_id, workspace_id)
        if ensure:
            self.ensure_derived(document_id, owner_id, workspace_id)
        return self.repo.events(document_id, event_type)

    def counts(self, document_id: str) -> dict:
        return {"chapters": len(self.repo.chapters(document_id)),
                "topics": len(self.repo.topics(document_id)),
                "events": len(self.repo.events(document_id))}
