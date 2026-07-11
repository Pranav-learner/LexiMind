"""Multimodal Workspace Orchestrator — the unifying coordination layer for all of Phases 1–4.

This service owns NO business logic and NO tables: it COORDINATES the existing domains. It aggregates
every knowledge asset (documents, extracted images/tables/figures, vision analyses, summaries, notes,
decks, conversations) into unified surfaces (asset explorer, timeline, pipeline status, overview), and
routes AI workspace actions to the existing generation services. Ingestion of new files (create +
text-index + auto multimodal processing + auto vision) is wired in the API layer where the runners
live. The point: the user never thinks about OCR/embeddings/retrieval/vision — they just upload and ask.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.mmworkspace.errors import DocumentNotFound, UnknownAction
from app.vision.validation import DIAGRAM_TYPES


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


class WorkspaceOrchestrator:
    def __init__(self, db: Session):
        self.db = db

    def _document(self, document_id: str, owner_id: str, workspace_id: str):
        from app.documents.repository import DocumentRepository
        doc = DocumentRepository(self.db).get(document_id, owner_id)
        if doc is None or doc.workspace_id != workspace_id:
            raise DocumentNotFound(document_id)
        return doc

    # ================================================================ asset explorer
    def assets(self, workspace_id: str, owner_id: str, *, asset_type: Optional[str] = None, limit: int = 60) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        counts: Dict[str, int] = {}

        def add(rows_kind, builder):
            kind, rows = rows_kind
            counts[kind] = counts.get(kind, 0) + len(rows)
            if asset_type in (None, kind):
                items.extend(builder(r) for r in rows)

        ws = workspace_id
        from app.chat.models import Conversation
        from app.documents.models import Document
        from app.flashcards.models import Deck
        from app.ingestion.models import ExtractedFigure, ExtractedImage, ExtractedTable
        from app.notes.models import Note
        from app.summaries.models import Summary
        from app.vision.models import VisionAnalysis

        docs = list(self.db.scalars(select(Document).where(Document.workspace_id == ws, Document.owner_id == owner_id, Document.deleted_at.is_(None)).order_by(desc(Document.created_at))))
        add(("document", docs), lambda d: {
            "id": d.id, "asset_type": "document", "modality": "text", "title": d.display_name,
            "subtitle": f"{d.page_count} pages · {d.file_type}", "document_id": d.id, "created_at": _iso(d.created_at),
            "route": f"/workspace/{ws}/document/{d.id}", "metadata": {"media_type": d.media_type}})

        # Vision analyses give the richest per-asset view (classification + caption); group by kind.
        analyses = list(self.db.scalars(select(VisionAnalysis).where(VisionAnalysis.workspace_id == ws).order_by(desc(VisionAnalysis.created_at))))
        diagrams = [a for a in analyses if a.image_type in DIAGRAM_TYPES]
        tables_v = [a for a in analyses if a.image_type == "table"]
        images_v = [a for a in analyses if a.image_type not in DIAGRAM_TYPES and a.image_type != "table"]

        def vis_item(kind):
            def build(a):
                return {"id": a.id, "asset_type": kind, "modality": kind, "title": a.image_type.replace("_", " "),
                        "subtitle": (a.caption or "")[:120], "document_id": a.document_id, "page_number": a.page_number,
                        "created_at": _iso(a.created_at), "route": f"/workspace/{ws}/document/{a.document_id}",
                        "thumbnail_url": f"/workspaces/{ws}/vision/analyses/{a.id}/thumbnail",
                        "metadata": {"confidence": a.confidence, "keywords": a.keywords}}
            return build
        add(("diagram", diagrams), vis_item("diagram"))
        add(("table", tables_v), vis_item("table"))
        add(("image", images_v), vis_item("image"))

        # Raw extracted figures/images not (yet) vision-analyzed still appear.
        figures = list(self.db.scalars(select(ExtractedFigure).where(ExtractedFigure.workspace_id == ws).order_by(desc(ExtractedFigure.created_at))))
        add(("figure", figures), lambda f: {
            "id": f.id, "asset_type": "figure", "modality": "figure", "title": f.figure_type,
            "subtitle": (f.caption or "")[:120], "document_id": f.document_id, "page_number": f.page_number,
            "created_at": _iso(f.created_at), "route": f"/workspace/{ws}/document/{f.document_id}", "metadata": {}})

        summaries = list(self.db.scalars(select(Summary).where(Summary.workspace_id == ws, Summary.deleted_at.is_(None)).order_by(desc(Summary.created_at))))
        add(("summary", summaries), lambda s: {"id": s.id, "asset_type": "summary", "modality": "mixed", "title": s.title,
            "subtitle": s.summary_type, "document_id": s.document_id, "created_at": _iso(s.created_at),
            "route": f"/workspace/{ws}/summaries/{s.id}", "metadata": {}})
        notes = list(self.db.scalars(select(Note).where(Note.workspace_id == ws, Note.deleted_at.is_(None)).order_by(desc(Note.created_at))))
        add(("note", notes), lambda n: {"id": n.id, "asset_type": "note", "modality": "mixed", "title": n.title,
            "subtitle": f"{n.word_count} words", "document_id": n.document_id, "created_at": _iso(n.created_at),
            "route": f"/workspace/{ws}/notes/{n.id}", "metadata": {}})
        decks = list(self.db.scalars(select(Deck).where(Deck.workspace_id == ws, Deck.deleted_at.is_(None)).order_by(desc(Deck.created_at))))
        add(("deck", decks), lambda d: {"id": d.id, "asset_type": "deck", "modality": "mixed", "title": d.name,
            "subtitle": f"{d.card_count} cards", "document_id": d.document_id, "created_at": _iso(d.created_at),
            "route": f"/workspace/{ws}/flashcards/deck/{d.id}", "metadata": {}})
        convs = list(self.db.scalars(select(Conversation).where(Conversation.workspace_id == ws, Conversation.deleted_at.is_(None)).order_by(desc(Conversation.created_at))))
        add(("conversation", convs), lambda c: {"id": c.id, "asset_type": "conversation", "modality": "mixed", "title": c.title,
            "subtitle": f"{c.message_count} messages", "document_id": None, "created_at": _iso(c.created_at),
            "route": f"/workspace/{ws}/chat/{c.id}", "metadata": {}})

        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return {"items": items[:limit], "total": len(items), "counts": counts}

    # ================================================================ timeline
    def timeline(self, workspace_id: str, owner_id: str, *, limit: int = 40) -> List[Dict[str, Any]]:
        ws = workspace_id
        events: List[Dict[str, Any]] = []
        from app.chat.models import Conversation
        from app.documents.models import Document
        from app.flashcards.models import Deck
        from app.ingestion.models import ProcessingJob
        from app.notes.models import Note
        from app.summaries.models import Summary
        from app.vision.models import VisionJob

        def collect(rows, type_, icon, title_fn, route_fn, ts="created_at"):
            for r in rows:
                events.append({"type": type_, "icon": icon, "title": title_fn(r),
                               "timestamp": _iso(getattr(r, ts)), "target_id": r.id, "route": route_fn(r)})

        collect(self.db.scalars(select(Document).where(Document.workspace_id == ws, Document.deleted_at.is_(None)).order_by(desc(Document.created_at)).limit(15)),
                "upload", "📤", lambda d: f"Uploaded “{d.display_name}”", lambda d: f"/workspace/{ws}/document/{d.id}")
        collect(self.db.scalars(select(ProcessingJob).where(ProcessingJob.workspace_id == ws, ProcessingJob.status == "completed").order_by(desc(ProcessingJob.updated_at)).limit(10)),
                "processing", "🧩", lambda j: f"Processed a document ({j.image_count} images, {j.table_count} tables)", lambda j: f"/workspace/{ws}/document/{j.document_id}", ts="updated_at")
        collect(self.db.scalars(select(VisionJob).where(VisionJob.workspace_id == ws, VisionJob.status == "completed").order_by(desc(VisionJob.updated_at)).limit(10)),
                "vision", "👁", lambda j: f"Understood {j.analyzed_count} visual assets", lambda j: f"/workspace/{ws}/document/{j.document_id}", ts="updated_at")
        collect(self.db.scalars(select(Summary).where(Summary.workspace_id == ws, Summary.deleted_at.is_(None)).order_by(desc(Summary.created_at)).limit(8)),
                "summary", "📄", lambda s: f"Summary “{s.title}”", lambda s: f"/workspace/{ws}/summaries/{s.id}")
        collect(self.db.scalars(select(Note).where(Note.workspace_id == ws, Note.deleted_at.is_(None)).order_by(desc(Note.created_at)).limit(8)),
                "note", "📝", lambda n: f"Note “{n.title}”", lambda n: f"/workspace/{ws}/notes/{n.id}")
        collect(self.db.scalars(select(Deck).where(Deck.workspace_id == ws, Deck.deleted_at.is_(None)).order_by(desc(Deck.created_at)).limit(8)),
                "deck", "🎴", lambda d: f"Deck “{d.name}”", lambda d: f"/workspace/{ws}/flashcards/deck/{d.id}")
        collect(self.db.scalars(select(Conversation).where(Conversation.workspace_id == ws, Conversation.deleted_at.is_(None)).order_by(desc(Conversation.created_at)).limit(8)),
                "chat", "💬", lambda c: f"Chat “{c.title}”", lambda c: f"/workspace/{ws}/chat/{c.id}")

        events.sort(key=lambda e: e["timestamp"] or "", reverse=True)
        return events[:limit]

    # ================================================================ pipeline status
    def pipeline_status(self, workspace_id: str, owner_id: str, document_id: str) -> Dict[str, Any]:
        doc = self._document(document_id, owner_id, workspace_id)
        from app.ingestion.repository import IngestionRepository
        from app.ingestion.service import IngestionService
        from app.vision.repository import VisionRepository
        from app.vision.service import VisionService

        proc = IngestionService(IngestionRepository(self.db)).status_for_document(document_id, owner_id, workspace_id)
        vis = VisionService(VisionRepository(self.db)).status_for_document(document_id, owner_id, workspace_id)
        ic = IngestionRepository(self.db).counts(document_id)
        from app.vision.models import VisionAnalysis
        vcount = int(self.db.scalar(select(func.count()).select_from(VisionAnalysis).where(VisionAnalysis.document_id == document_id)) or 0)

        proc_summary = {"status": proc.status, "stage": proc.stage, "progress": proc.progress,
                        "image_count": proc.image_count, "table_count": proc.table_count,
                        "figure_count": proc.figure_count, "chunk_count": proc.chunk_count, "ocr_pages": proc.ocr_pages} if proc else None
        vis_summary = {"status": vis.status, "analyzed_count": vis.analyzed_count, "embedding_count": vis.embedding_count} if vis else None
        ready = (proc is not None and proc.status == "completed") and (vis is None or vis.status in ("completed",)) and doc.processing_status == "ready"

        return {
            "document_id": document_id, "display_name": doc.display_name,
            "text_indexed": doc.indexing_status == "indexed" or doc.processing_status == "ready",
            "processing": proc_summary, "vision": vis_summary,
            "counts": {"ocr_pages": proc.ocr_pages if proc else 0,
                       "images": ic.get("images", 0), "tables": ic.get("tables", 0),
                       "figures": ic.get("figures", 0), "chunks": ic.get("chunks", 0), "vision_assets": vcount},
            "ready": bool(ready),
        }

    # ================================================================ AI workspace actions
    def ai_action(self, workspace_id: str, owner_id: str, action: str, document_id: str, *,
                  focus: Optional[str] = None, count: Optional[int] = None,
                  summary_runner=None, notes_runner=None, flashcard_runner=None) -> Dict[str, Any]:
        """Route a multimodal AI action to the existing generation service (reuse, never duplicate)."""
        doc = self._document(document_id, owner_id, workspace_id)
        subject = f"{focus} in {doc.display_name}" if focus else doc.display_name
        ws = workspace_id

        if action == "summary":
            from app.summaries.repository import SummaryRepository
            from app.summaries.service import SummaryService
            from app.workspaces.repository import WorkspaceRepository
            from app.workspaces.service import WorkspaceService
            svc = SummaryService(SummaryRepository(self.db), WorkspaceService(WorkspaceRepository(self.db)))
            s = svc.create(owner_id, ws, summary_type="standard", scope="document", document_id=document_id, subject=subject)
            if summary_runner:
                summary_runner.submit(s.id)
            return {"action": action, "asset_type": "summary", "asset_id": s.id, "status": self._reload_status("summary", s.id), "route": f"/workspace/{ws}/summaries/{s.id}"}

        if action == "notes":
            from app.notes.repository import NoteRepository
            from app.notes.service import NoteService
            from app.workspaces.repository import WorkspaceRepository
            from app.workspaces.service import WorkspaceService
            svc = NoteService(NoteRepository(self.db), WorkspaceService(WorkspaceRepository(self.db)))
            n = svc.create_generated(owner_id, ws, note_type="study", scope="document", document_id=document_id, subject=subject)
            if notes_runner:
                notes_runner.submit(n.id)
            return {"action": action, "asset_type": "note", "asset_id": n.id, "status": self._reload_status("note", n.id), "route": f"/workspace/{ws}/notes/{n.id}"}

        if action == "flashcards":
            from app.flashcards.repository import FlashcardRepository
            from app.flashcards.service import FlashcardService
            from app.workspaces.repository import WorkspaceRepository
            from app.workspaces.service import WorkspaceService
            svc = FlashcardService(FlashcardRepository(self.db), WorkspaceService(WorkspaceRepository(self.db)))
            d = svc.generate_deck(owner_id, ws, scope="document", document_id=document_id, subject=subject, count=count or 10)
            if flashcard_runner:
                flashcard_runner.submit(d.id)
            return {"action": action, "asset_type": "deck", "asset_id": d.id, "status": self._reload_status("deck", d.id), "route": f"/workspace/{ws}/flashcards/deck/{d.id}"}

        raise UnknownAction(action)

    def _reload_status(self, kind: str, asset_id: str) -> str:
        from app.flashcards.models import Deck
        from app.notes.models import Note
        from app.summaries.models import Summary
        model = {"summary": Summary, "note": Note, "deck": Deck}[kind]
        row = self.db.get(model, asset_id)
        if row is not None:
            # A background runner (its own session) may have advanced the status → refresh from DB.
            self.db.refresh(row)
        return row.status if row else "queued"

    # ================================================================ overview / observability
    def overview(self, workspace_id: str, owner_id: str) -> Dict[str, Any]:
        ws = workspace_id
        from app.chat.models import Conversation
        from app.documents.models import Document
        from app.flashcards.models import Deck
        from app.ingestion.models import MultimodalChunk, ProcessingJob
        from app.mmcontext.models import ContextBuildLog
        from app.mmretrieval.models import RetrievalLog
        from app.notes.models import Note
        from app.summaries.models import Summary
        from app.vision.models import VisionAnalysis, VisionEmbedding, VisionJob
        from app.workspaces.models import Workspace

        def c(model, *conds):
            return int(self.db.scalar(select(func.count()).select_from(model).where(*conds)) or 0)

        from app.ingestion.models import ExtractedFigure
        wsrow = self.db.get(Workspace, ws)
        analyses = list(self.db.scalars(select(VisionAnalysis.image_type).where(VisionAnalysis.workspace_id == ws)))
        diagrams = sum(1 for t in analyses if t in DIAGRAM_TYPES)
        tables_v = sum(1 for t in analyses if t == "table")
        images_v = len(analyses) - diagrams - tables_v

        return {
            "workspace_id": ws, "name": wsrow.name if wsrow else "Workspace",
            "assets": {
                "documents": c(Document, Document.workspace_id == ws, Document.deleted_at.is_(None)),
                "images": images_v, "diagrams": diagrams, "tables": tables_v,
                "figures": c(ExtractedFigure, ExtractedFigure.workspace_id == ws),
                "summaries": c(Summary, Summary.workspace_id == ws, Summary.deleted_at.is_(None)),
                "notes": c(Note, Note.workspace_id == ws, Note.deleted_at.is_(None)),
                "decks": c(Deck, Deck.workspace_id == ws, Deck.deleted_at.is_(None)),
                "chats": c(Conversation, Conversation.workspace_id == ws, Conversation.deleted_at.is_(None)),
            },
            "modalities": {
                "text_chunks": c(MultimodalChunk, MultimodalChunk.workspace_id == ws, MultimodalChunk.chunk_type.in_(["text", "ocr"])),
                "ocr_pages": c(MultimodalChunk, MultimodalChunk.workspace_id == ws, MultimodalChunk.chunk_type == "ocr"),
                "vision_assets": len(analyses),
                "vision_embeddings": c(VisionEmbedding, VisionEmbedding.workspace_id == ws),
            },
            "pipelines": {
                "processed_documents": c(ProcessingJob, ProcessingJob.workspace_id == ws, ProcessingJob.status == "completed"),
                "vision_analyzed": c(VisionJob, VisionJob.workspace_id == ws, VisionJob.status == "completed"),
                "pending_embeddings": c(MultimodalChunk, MultimodalChunk.workspace_id == ws, MultimodalChunk.embedding_status == "pending"),
            },
            "activity": {
                "searches": c(RetrievalLog, RetrievalLog.workspace_id == ws),
                "context_builds": c(ContextBuildLog, ContextBuildLog.workspace_id == ws),
            },
            "ready_documents": c(Document, Document.workspace_id == ws, Document.deleted_at.is_(None), Document.processing_status == "ready"),
        }
