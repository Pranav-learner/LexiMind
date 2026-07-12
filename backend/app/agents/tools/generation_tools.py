"""Generation/write tools — thin wrappers over the EXISTING knowledge-asset services.

Each enqueues generation through the same service + async runner the rest of LexiMind uses (reuse,
never duplicate) and returns the created asset id/status/route. The injected runner comes from
`ctx.services` so tools never import FastAPI/runners (tests inject inline runners; prod injects the
threadpool runners). These tools require the `generate`/`write` permission.
"""

from __future__ import annotations

from typing import Any, Dict

from app.agents.interfaces import ToolParam, ToolResult, ToolSpec
from app.agents.tools.base import BaseTool


def _subject(ctx, args) -> str:
    return args.get("subject") or args.get("focus") or ctx.query


def _ws_service(ctx):
    from app.workspaces.repository import WorkspaceRepository
    from app.workspaces.service import WorkspaceService
    return WorkspaceService(WorkspaceRepository(ctx.db))


class GenerateSummaryTool(BaseTool):
    spec = ToolSpec(
        name="generate_summary", version="1.0", category="generation",
        description="Generate a summary asset for a document/recording (reuses the summaries service).",
        params=[ToolParam("document_id", "string", False, "Target document (defaults to scope)."),
                ToolParam("summary_type", "string", False, "quick|standard|detailed|bullet|chapterwise")],
        permissions=["generate", "write"], parallel_safe=False, cost_weight=2.0)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.summaries.repository import SummaryRepository
        from app.summaries.service import SummaryService
        doc_id = args.get("document_id") or ctx.document_id
        svc = SummaryService(SummaryRepository(ctx.db), _ws_service(ctx))
        s = svc.create(ctx.owner_id, ctx.workspace_id, summary_type=args.get("summary_type", "standard"),
                       scope="document" if doc_id else "workspace", document_id=doc_id, subject=_subject(ctx, args))
        runner = ctx.services.get("summary_runner")
        if runner:
            runner.submit(s.id)
        row = ctx.db.get(type(s), s.id)
        if row is not None:
            ctx.db.refresh(row)
        return self._result(output={"asset_type": "summary", "asset_id": s.id,
                                    "status": getattr(row, "status", "queued"),
                                    "route": f"/workspace/{ctx.workspace_id}/summaries/{s.id}"},
                            context_text=f"Queued a summary ({s.id}).")


class GenerateNotesTool(BaseTool):
    spec = ToolSpec(
        name="generate_notes", version="1.0", category="generation",
        description="Generate study notes for a document/recording (reuses the notes service).",
        params=[ToolParam("document_id", "string", False, "Target document (defaults to scope)."),
                ToolParam("note_type", "string", False, "quick|study|detailed|chapterwise|concept|revision")],
        permissions=["generate", "write"], parallel_safe=False, cost_weight=2.0)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.notes.repository import NoteRepository
        from app.notes.service import NoteService
        doc_id = args.get("document_id") or ctx.document_id
        svc = NoteService(NoteRepository(ctx.db), _ws_service(ctx))
        n = svc.create_generated(ctx.owner_id, ctx.workspace_id, note_type=args.get("note_type", "study"),
                                 scope="document" if doc_id else "workspace", document_id=doc_id, subject=_subject(ctx, args))
        runner = ctx.services.get("notes_runner")
        if runner:
            runner.submit(n.id)
        row = ctx.db.get(type(n), n.id)
        if row is not None:
            ctx.db.refresh(row)
        return self._result(output={"asset_type": "note", "asset_id": n.id,
                                    "status": getattr(row, "status", "queued"),
                                    "route": f"/workspace/{ctx.workspace_id}/notes/{n.id}"},
                            context_text=f"Queued study notes ({n.id}).")


class GenerateFlashcardsTool(BaseTool):
    spec = ToolSpec(
        name="generate_flashcards", version="1.0", category="generation",
        description="Generate a flashcard deck for a document/recording (reuses the flashcards service).",
        params=[ToolParam("document_id", "string", False, "Target document (defaults to scope)."),
                ToolParam("count", "integer", False, "Number of cards (default 10).")],
        permissions=["generate", "write"], parallel_safe=False, cost_weight=2.5)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.flashcards.repository import FlashcardRepository
        from app.flashcards.service import FlashcardService
        doc_id = args.get("document_id") or ctx.document_id
        svc = FlashcardService(FlashcardRepository(ctx.db), _ws_service(ctx))
        d = svc.generate_deck(ctx.owner_id, ctx.workspace_id, scope="document" if doc_id else "workspace",
                              document_id=doc_id, subject=_subject(ctx, args), count=int(args.get("count", 10)))
        runner = ctx.services.get("flashcard_runner")
        if runner:
            runner.submit(d.id)
        row = ctx.db.get(type(d), d.id)
        if row is not None:
            ctx.db.refresh(row)
        return self._result(output={"asset_type": "deck", "asset_id": d.id,
                                    "status": getattr(row, "status", "queued"),
                                    "route": f"/workspace/{ctx.workspace_id}/flashcards/deck/{d.id}"},
                            context_text=f"Queued a flashcard deck ({d.id}).")


class CreateNoteTool(BaseTool):
    """Create a blank note the user can edit (reuses the notes service; no generation)."""

    spec = ToolSpec(
        name="create_note", version="1.0", category="write",
        description="Create a new empty note in the workspace.",
        params=[ToolParam("title", "string", False, "Note title.")],
        permissions=["write"], parallel_safe=False, cost_weight=0.5)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.notes.repository import NoteRepository
        from app.notes.service import NoteService
        svc = NoteService(NoteRepository(ctx.db), _ws_service(ctx))
        n = svc.create(ctx.owner_id, ctx.workspace_id, title=args.get("title") or "New note", source="blank")
        return self._result(output={"asset_type": "note", "asset_id": n.id,
                                    "route": f"/workspace/{ctx.workspace_id}/notes/{n.id}"},
                            context_text=f"Created a note ({n.id}).")
