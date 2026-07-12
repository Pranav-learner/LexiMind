"""Media AI Workspace Orchestrator (Phase 5, Module 4) — the product-integration coordination layer.

Like the Phase-4 `mmworkspace` orchestrator, this owns NO business logic and NO retrieval/generation
pipelines. It COORDINATES the existing domains into one seamless media experience:

- `overview` / `library`      — media + temporal-intelligence stats (reuse media/tintel/tretrieval repos).
- `unified_timeline`          — merge chapters + topics + events + speakers + scenes into one ordered,
                                lane-based timeline (reuse tintel + media rows). Interactive-timeline data.
- `playback_meta`             — everything the player needs (duration/kind/url/chapters/speakers).
- `media_chat`                — reuse the EXISTING ChatService.run_message with an injected
                                TemporalChatEngine (temporal retrieval → prompt → answer_service).
- `ai_action`                 — route knowledge-asset generation to the existing summaries/notes/
                                flashcards services + runners (reuse, never duplicate) with temporal subject.
- `search`                    — unified: temporal retrieval ⊕ multimodal document retrieval.
- observability               — record + aggregate MediaInteractionEvent telemetry (Step 15).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.mediaworkspace.errors import MediaNotFound, UnknownAction
from app.mediaworkspace.models import MediaInteractionEvent
from app.mediaworkspace.repository import MediaWorkspaceRepository


def _fmt(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{(s % 3600) // 60:02d}:{s % 60:02d}"


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


# Knowledge-asset actions → existing service + a valid type (reuse; no new generation logic).
# The intent that has no dedicated type is carried in the `subject`/`focus` so the same prompt
# builders produce the right asset (e.g. "meeting minutes of …").
_ACTION_MAP = {
    "summary": ("summary", {"summary_type": "standard"}),
    "minutes": ("summary", {"summary_type": "standard", "label": "Meeting minutes"}),
    "chapterwise": ("summary", {"summary_type": "chapterwise"}),
    "notes": ("notes", {"note_type": "study"}),
    "study_guide": ("notes", {"note_type": "study", "label": "Study guide"}),
    "revision": ("notes", {"note_type": "revision", "label": "Revision notes"}),
    "action_items": ("notes", {"note_type": "quick", "label": "Action items"}),
    "key_decisions": ("notes", {"note_type": "quick", "label": "Key decisions"}),
    "flashcards": ("flashcards", {}),
}


class MediaWorkspaceOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MediaWorkspaceRepository(db)

    # ================================================================ helpers
    def _document(self, document_id: str, owner_id: str, workspace_id: str):
        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise MediaNotFound(document_id)
        return doc

    def _latest_job(self, document_id: str):
        from app.media.models import MediaJob
        return self.db.scalar(select(MediaJob).where(MediaJob.document_id == document_id)
                              .order_by(MediaJob.created_at.desc()).limit(1))

    # ================================================================ overview / library
    def overview(self, workspace_id: str, owner_id: str) -> Dict[str, Any]:
        ws = workspace_id
        from app.documents.models import Document
        from app.media.models import MediaFrame, MediaJob, Scene, Speaker, TranscriptSegment
        from app.tintel.models import Chapter, TimelineEvent, Topic
        from app.tretrieval.models import TemporalSearchLog

        def c(model, *conds):
            return int(self.db.scalar(select(func.count()).select_from(model).where(*conds)) or 0)

        media_docs = list(self.db.scalars(select(Document).where(
            Document.workspace_id == ws, Document.owner_id == owner_id, Document.deleted_at.is_(None),
            Document.media_type.in_(["audio", "video"]))))
        audio = sum(1 for d in media_docs if d.media_type == "audio")
        video = sum(1 for d in media_docs if d.media_type == "video")
        total_duration = int(self.db.scalar(
            select(func.coalesce(func.sum(MediaJob.duration_ms), 0)).where(
                MediaJob.workspace_id == ws, MediaJob.status == "completed")) or 0)
        media_chats = self.repo.total(ws, "media_chat")

        return {
            "workspace_id": ws, "recordings": len(media_docs), "audio": audio, "video": video,
            "total_duration_ms": total_duration,
            "transcript_segments": c(TranscriptSegment, TranscriptSegment.workspace_id == ws),
            "speakers": c(Speaker, Speaker.workspace_id == ws),
            "chapters": c(Chapter, Chapter.workspace_id == ws),
            "topics": c(Topic, Topic.workspace_id == ws),
            "events": c(TimelineEvent, TimelineEvent.workspace_id == ws),
            "scenes": c(Scene, Scene.workspace_id == ws),
            "frames": c(MediaFrame, MediaFrame.workspace_id == ws),
            "temporal_searches": c(TemporalSearchLog, TemporalSearchLog.workspace_id == ws),
            "media_chats": media_chats,
            "interactions": self.repo.usage(ws),
        }

    def library(self, workspace_id: str, owner_id: str, *, limit: int = 100) -> Dict[str, Any]:
        from app.documents.models import Document
        from app.media.models import Speaker
        from app.tintel.models import Chapter

        docs = list(self.db.scalars(select(Document).where(
            Document.workspace_id == workspace_id, Document.owner_id == owner_id,
            Document.deleted_at.is_(None), Document.media_type.in_(["audio", "video"]))
            .order_by(Document.created_at.desc()).limit(limit)))
        items: List[Dict[str, Any]] = []
        for d in docs:
            job = self._latest_job(d.id)
            spk = int(self.db.scalar(select(func.count()).select_from(Speaker)
                                     .where(Speaker.document_id == d.id)) or 0)
            chap = int(self.db.scalar(select(func.count()).select_from(Chapter)
                                      .where(Chapter.document_id == d.id)) or 0)
            items.append({
                "document_id": d.id, "display_name": d.display_name, "media_kind": d.media_type,
                "duration_ms": int(getattr(job, "duration_ms", 0) or 0),
                "processing_status": d.processing_status,
                "intelligence_ready": chap > 0,
                "speaker_count": spk, "chapter_count": chap, "created_at": _iso(d.created_at)})
        return {"items": items, "total": len(items)}

    # ================================================================ unified interactive timeline
    def unified_timeline(self, workspace_id: str, owner_id: str, document_id: str) -> Dict[str, Any]:
        """Merge chapters/topics/events/speaker-turns/scenes into one lane-based, ordered timeline.
        Ensures temporal intelligence is derived first (reuses tintel's ensure_derived)."""
        self._document(document_id, owner_id, workspace_id)
        from app.tintel.repository import TemporalIntelRepository
        from app.tintel.service import TemporalIntelService
        TemporalIntelService(TemporalIntelRepository(self.db)).ensure_derived(document_id, owner_id, workspace_id)

        from app.media.models import Scene, SpeakerTurn
        from app.tintel.models import Chapter, TimelineEvent, Topic

        job = self._latest_job(document_id)
        duration = int(getattr(job, "duration_ms", 0) or 0)
        items: List[Dict[str, Any]] = []

        def span(start, end):
            return f"{_fmt(int(start))}–{_fmt(int(end))}"

        for ch in self.db.scalars(select(Chapter).where(Chapter.document_id == document_id).order_by(Chapter.start_ms)):
            items.append({"kind": "chapter", "id": ch.id, "title": ch.title, "start_ms": ch.start_ms,
                          "end_ms": ch.end_ms, "timespan": span(ch.start_ms, ch.end_ms), "lane": "chapters",
                          "metadata": {"keywords": ch.keywords, "source": ch.source}})
        for tp in self.db.scalars(select(Topic).where(Topic.document_id == document_id).order_by(Topic.start_ms)):
            items.append({"kind": "topic", "id": tp.id, "title": tp.label, "start_ms": tp.start_ms,
                          "end_ms": tp.end_ms, "timespan": span(tp.start_ms, tp.end_ms), "lane": "topics",
                          "metadata": {"salience": tp.salience}})
        for ev in self.db.scalars(select(TimelineEvent).where(TimelineEvent.document_id == document_id).order_by(TimelineEvent.timestamp_ms)):
            items.append({"kind": "event", "id": ev.id, "title": ev.title, "start_ms": ev.start_ms,
                          "end_ms": ev.end_ms, "timespan": span(ev.start_ms, ev.end_ms), "lane": "events",
                          "metadata": {"event_type": ev.event_type, "at": _fmt(ev.timestamp_ms)}})
        for tn in self.db.scalars(select(SpeakerTurn).where(SpeakerTurn.document_id == document_id).order_by(SpeakerTurn.start_ms)):
            items.append({"kind": "speaker", "id": tn.id, "title": tn.speaker_label, "start_ms": tn.start_ms,
                          "end_ms": tn.end_ms, "timespan": span(tn.start_ms, tn.end_ms), "lane": "speakers",
                          "metadata": {"speaker_id": tn.speaker_id}})
        for sc in self.db.scalars(select(Scene).where(Scene.document_id == document_id).order_by(Scene.start_ms)):
            items.append({"kind": "scene", "id": sc.id, "title": f"Scene {sc.scene_index + 1}", "start_ms": sc.start_ms,
                          "end_ms": sc.end_ms, "timespan": span(sc.start_ms, sc.end_ms), "lane": "scenes",
                          "metadata": {"representative_frame_id": sc.representative_frame_id}})

        items.sort(key=lambda x: (x["start_ms"], x["lane"]))
        lanes = [l for l in ["chapters", "topics", "events", "speakers", "scenes"]
                 if any(i["lane"] == l for i in items)]
        if not duration and items:
            duration = max(i["end_ms"] for i in items)
        return {"document_id": document_id, "duration_ms": duration, "items": items, "lanes": lanes}

    # ================================================================ playback metadata
    def playback_meta(self, workspace_id: str, owner_id: str, document_id: str) -> Dict[str, Any]:
        doc = self._document(document_id, owner_id, workspace_id)
        from app.media.models import Scene, Speaker
        from app.tintel.models import Chapter
        job = self._latest_job(document_id)

        def n(model):
            return int(self.db.scalar(select(func.count()).select_from(model)
                                      .where(model.document_id == document_id)) or 0)
        return {
            "document_id": document_id, "media_kind": doc.media_type,
            "duration_ms": int(getattr(job, "duration_ms", 0) or 0),
            "media_url": f"/workspaces/{workspace_id}/documents/{document_id}/file",
            "chapters": n(Chapter), "speakers": n(Speaker), "scenes": n(Scene),
            "processing_status": doc.processing_status,
        }

    # ================================================================ media AI chat (reuse chat pipeline)
    def media_chat(self, owner_id: str, workspace_id: str, *, content: str, engine,
                   conversation_id: Optional[str] = None, document_id: Optional[str] = None,
                   top_k: Optional[int] = None) -> Dict[str, Any]:
        """Run one media chat turn through the EXISTING ChatService.run_message with a TemporalChatEngine.
        Reuses Conversation/Message/MessageCitation persistence + history + the single answer service."""
        from app.chat.repository import ConversationRepository, MessageRepository
        from app.chat.service import ChatService
        from app.workspaces.repository import WorkspaceRepository
        from app.workspaces.service import WorkspaceService

        chat = ChatService(ConversationRepository(self.db), MessageRepository(self.db),
                           WorkspaceService(WorkspaceRepository(self.db)))
        if document_id:
            self._document(document_id, owner_id, workspace_id)

        if conversation_id:
            conv = chat.get(conversation_id, owner_id)
        else:
            title = "Media chat"
            conv = chat.create(owner_id, workspace_id, title=title,
                               document_scope=[document_id] if document_id else None)

        user_msg = assistant_msg = None
        ok = True
        for ev in chat.run_message(conv.id, owner_id, content, engine, top_k=top_k):
            if ev["type"] == "user":
                user_msg = ev["message"]
            elif ev["type"] == "done":
                assistant_msg = ev["message"]
            elif ev["type"] == "error":
                assistant_msg = ev["message"]
                ok = False

        last = getattr(engine, "last_result", {}) or {}
        rich = last.get("citations", [])
        answer = assistant_msg.content if assistant_msg is not None else ""

        self.record_interaction(owner_id, workspace_id, event_type="media_chat", document_id=document_id,
                                target=conv.id, meta={"grounded": last.get("grounded", False)})
        return {
            "ok": ok, "conversation_id": conv.id, "document_id": document_id, "answer": answer,
            "grounded": bool(last.get("grounded", False)),
            "citations": [{
                "index": c.get("index"), "document_id": c.get("document_id"), "modality": c.get("modality"),
                "start_ms": int(c.get("start_ms", 0)), "end_ms": int(c.get("end_ms", 0)),
                "timespan": c.get("timespan", ""), "speaker_label": c.get("speaker_label", ""),
                "scene_id": c.get("scene_id"), "frame_id": c.get("frame_id"), "text": c.get("text", ""),
            } for c in rich],
            "primary": last.get("primary"),
            "retrieval_ms": int(getattr(assistant_msg, "retrieval_ms", 0) or 0),
            "latency_ms": int(getattr(assistant_msg, "latency_ms", 0) or 0),
            "context_size": int(getattr(assistant_msg, "context_size", 0) or 0),
            "user_message_id": getattr(user_msg, "id", None),
            "assistant_message_id": getattr(assistant_msg, "id", None),
        }

    # ================================================================ knowledge-asset AI actions
    def ai_action(self, workspace_id: str, owner_id: str, action: str, document_id: str, *,
                  focus: Optional[str] = None, count: Optional[int] = None,
                  summary_runner=None, notes_runner=None, flashcard_runner=None) -> Dict[str, Any]:
        """Route knowledge-asset generation to the EXISTING services (reuse, never duplicate)."""
        doc = self._document(document_id, owner_id, workspace_id)
        mapping = _ACTION_MAP.get(action)
        if mapping is None:
            raise UnknownAction(action)
        target, opts = mapping
        label = opts.get("label")
        base = f"{label} — {doc.display_name}" if label else doc.display_name
        subject = f"{focus} in {doc.display_name}" if focus else base
        ws = workspace_id

        if target == "summary":
            from app.summaries.repository import SummaryRepository
            from app.summaries.service import SummaryService
            from app.workspaces.repository import WorkspaceRepository
            from app.workspaces.service import WorkspaceService
            svc = SummaryService(SummaryRepository(self.db), WorkspaceService(WorkspaceRepository(self.db)))
            s = svc.create(owner_id, ws, summary_type=opts["summary_type"], scope="document",
                           document_id=document_id, subject=subject)
            if summary_runner:
                summary_runner.submit(s.id)
            result = {"action": action, "asset_type": "summary", "asset_id": s.id,
                      "status": self._reload_status("summary", s.id), "route": f"/workspace/{ws}/summaries/{s.id}"}

        elif target == "notes":
            from app.notes.repository import NoteRepository
            from app.notes.service import NoteService
            from app.workspaces.repository import WorkspaceRepository
            from app.workspaces.service import WorkspaceService
            svc = NoteService(NoteRepository(self.db), WorkspaceService(WorkspaceRepository(self.db)))
            n = svc.create_generated(owner_id, ws, note_type=opts["note_type"], scope="document",
                                     document_id=document_id, subject=subject)
            if notes_runner:
                notes_runner.submit(n.id)
            result = {"action": action, "asset_type": "note", "asset_id": n.id,
                      "status": self._reload_status("note", n.id), "route": f"/workspace/{ws}/notes/{n.id}"}

        else:  # flashcards
            from app.flashcards.repository import FlashcardRepository
            from app.flashcards.service import FlashcardService
            from app.workspaces.repository import WorkspaceRepository
            from app.workspaces.service import WorkspaceService
            svc = FlashcardService(FlashcardRepository(self.db), WorkspaceService(WorkspaceRepository(self.db)))
            d = svc.generate_deck(owner_id, ws, scope="document", document_id=document_id,
                                  subject=subject, count=count or 10)
            if flashcard_runner:
                flashcard_runner.submit(d.id)
            result = {"action": action, "asset_type": "deck", "asset_id": d.id,
                      "status": self._reload_status("deck", d.id), "route": f"/workspace/{ws}/flashcards/deck/{d.id}"}

        self.record_interaction(owner_id, ws, event_type="ai_action", document_id=document_id,
                                target=action, meta={"asset_type": result["asset_type"]})
        return result

    def _reload_status(self, kind: str, asset_id: str) -> str:
        from app.flashcards.models import Deck
        from app.notes.models import Note
        from app.summaries.models import Summary
        model = {"summary": Summary, "note": Note, "deck": Deck}[kind]
        row = self.db.get(model, asset_id)
        if row is not None:
            self.db.refresh(row)  # a bg runner (own session) may have advanced status
        return row.status if row else "queued"

    # ================================================================ unified cross-modal search
    def search(self, owner_id: str, workspace_id: str, query: str, *, top_k: int = 10,
               document_id: Optional[str] = None) -> Dict[str, Any]:
        """Unified media search: temporal moments ⊕ document/vision assets. Reuses both engines."""
        started = time.perf_counter()
        temporal: List[Dict[str, Any]] = []
        documents: List[Dict[str, Any]] = []
        try:
            from app.tretrieval.repository import TemporalRepository
            from app.tretrieval.schemas import TemporalSearchRequest
            from app.tretrieval.service import TemporalRetrievalService
            tsvc = TemporalRetrievalService(TemporalRepository(self.db))
            tres = tsvc.search(owner_id, workspace_id, TemporalSearchRequest(
                query=query, document_id=document_id, top_k=top_k, build_context=False, explain=False))
            temporal = tres.get("results", [])
        except Exception:
            temporal = []
        try:
            from app.mmretrieval.repository import RetrievalRepository
            from app.mmretrieval.schemas import SearchRequest
            from app.mmretrieval.service import MultimodalRetrievalService
            msvc = MultimodalRetrievalService(RetrievalRepository(self.db))
            mres = msvc.search(owner_id, workspace_id, SearchRequest(
                query=query, top_k=top_k, document_id=document_id, explain=False))
            documents = mres.get("results", [])
        except Exception:
            documents = []

        self.record_interaction(owner_id, workspace_id, event_type="media_search", target=query[:200])
        return {"query": query, "total": len(temporal) + len(documents), "temporal": temporal,
                "documents": documents, "total_ms": round((time.perf_counter() - started) * 1000, 3)}

    # ================================================================ observability (Step 15)
    def record_interaction(self, owner_id: str, workspace_id: str, *, event_type: str,
                           document_id: Optional[str] = None, target: Optional[str] = None,
                           position_ms: Optional[int] = None, meta: Optional[Dict[str, Any]] = None):
        return self.repo.record(MediaInteractionEvent(
            workspace_id=workspace_id, owner_id=owner_id, document_id=document_id,
            event_type=event_type, target=(target or None), position_ms=position_ms, meta=meta))

    def observability(self, workspace_id: str) -> Dict[str, Any]:
        recent = self.repo.recent(workspace_id, limit=20)
        return {
            "workspace_id": workspace_id, "usage": self.repo.usage(workspace_id),
            "total": self.repo.total(workspace_id),
            "recent": [{"event_type": r.event_type, "document_id": r.document_id, "target": r.target,
                        "position_ms": r.position_ms, "created_at": _iso(r.created_at)} for r in recent],
        }
