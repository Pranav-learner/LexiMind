"""Summary business logic — lifecycle + the generation pipeline.

`create` enqueues a summary (status=queued); a background runner later calls `generate_now`, which
consumes the injected engine's events, persists each section + its citations, tracks progress, and
honors cancellation. The engine (not this service) does retrieval/context/LLM — reused, not forked.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.summaries import validation
from app.summaries.errors import SummaryNotFound, SummaryStateError
from app.summaries.models import Summary, SummaryCitation, SummarySection
from app.summaries.repository import SummaryRepository
from app.summaries.schemas import SortField, SortOrder, StatusFilter


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SummaryService:
    def __init__(self, repo: SummaryRepository, workspace_service=None):
        self.repo = repo
        self.workspace_service = workspace_service

    # ------------------------------------------------------------------ helpers
    def _get_or_404(self, summary_id: str, owner_id: str) -> Summary:
        s = self.repo.get(summary_id, owner_id)
        if s is None:
            raise SummaryNotFound(summary_id)
        return s

    def _bump_ws(self, workspace_id: str, owner_id: str, delta: int) -> None:
        if self.workspace_service is None:
            return
        try:
            self.workspace_service.adjust_counter(workspace_id, owner_id, "summary_count", delta)
        except Exception:
            pass

    # ------------------------------------------------------------------ create / enqueue
    def create(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        summary_type: str,
        scope: Optional[str] = None,
        document_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        title: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> Summary:
        summary_type = validation.validate_summary_type(summary_type)
        scope = validation.validate_scope(scope, document_id=document_id, document_ids=document_ids)
        title = validation.validate_title(
            title, default=validation.default_title(summary_type, scope=scope, subject=subject)
        )
        s = Summary(
            owner_id=owner_id,
            workspace_id=workspace_id,
            scope=scope,
            document_id=document_id if scope == "document" else None,
            document_ids=document_ids if scope == "multi" else None,
            title=title,
            summary_type=summary_type,
            status="queued",
            stage="queued",
            progress=0,
        )
        s = self.repo.create(s)
        self._bump_ws(workspace_id, owner_id, +1)
        return s

    # ------------------------------------------------------------------ the generation pipeline
    def generate_now(self, summary_id: str, engine) -> Summary:
        """Run generation for a queued summary. Called by the background runner (trusted id).

        Idempotent w.r.t. sections: clears any prior sections first (so a regenerate/retry is
        clean). Persists sections + citations as they arrive, tracks progress, and stops early if
        the summary was cancelled mid-flight.
        """
        summary = self.repo.get_by_id_only(summary_id)
        if summary is None:
            return None  # deleted before the worker started
        if summary.status == "cancelled":
            return summary

        started = time.perf_counter()
        self.repo.clear_sections(summary.id)
        summary.status = "processing"
        summary.stage = "retrieving"
        summary.progress = 1
        summary.error = None
        self.repo.save(summary)

        total = 1
        done = 0
        try:
            for ev in engine.generate(summary, self.repo.db):
                etype = ev.get("type")
                if etype == "plan":
                    total = max(1, int(ev.get("total", 1)))
                    if ev.get("model"):
                        summary.model_name = ev["model"]
                    if ev.get("language"):
                        summary.language = ev["language"]
                    self.repo.save(summary)
                elif etype == "section":
                    # Cancellation check between sections.
                    self.repo.db.refresh(summary)
                    if summary.status == "cancelled":
                        summary.stage = "cancelled"
                        self.repo.save(summary)
                        return summary
                    self._persist_section(summary, ev)
                    done += 1
                    summary.progress = min(99, int(done / total * 100))
                    summary.stage = f"section {done}/{total}"
                    summary.section_count = done
                    self.repo.save(summary)
                elif etype == "final":
                    summary.token_usage = int(ev.get("token_usage", 0))
        except Exception as e:  # failure recovery — persist the error, keep partial sections
            summary.status = "failed"
            summary.stage = "failed"
            summary.error = str(e)[:4000]
            self.repo.save(summary)
            return summary

        if summary.status != "cancelled":
            summary.status = "completed"
            summary.stage = "completed"
            summary.progress = 100
            summary.generation_ms = int((time.perf_counter() - started) * 1000)
            self.repo.save(summary)
        return summary

    def _persist_section(self, summary: Summary, ev: Dict[str, Any]) -> None:
        cits = ev.get("citations", []) or []
        section = SummarySection(
            summary_id=summary.id,
            heading=(ev.get("heading") or "")[:300],
            order=int(ev.get("order", 0)),
            content=ev.get("content", "") or "",
            citation_count=len(cits),
        )
        citation_rows = [
            SummaryCitation(
                summary_section_id=section.id,
                document_id=c.get("document_id"),
                chunk_id=c.get("chunk_id"),
                page_number=c.get("page_number"),
                workspace_id=summary.workspace_id,
                citation_text=(c.get("text") or c.get("source") or "")[:2000],
                confidence=c.get("confidence"),
            )
            for c in cits
        ]
        self.repo.add_section(section, citation_rows)

    # ------------------------------------------------------------------ commands
    def rename(self, summary_id: str, owner_id: str, title: str) -> Summary:
        s = self._get_or_404(summary_id, owner_id)
        s.title = validation.validate_title(title, default=s.title)
        return self.repo.save(s)

    def cancel(self, summary_id: str, owner_id: str) -> Summary:
        s = self._get_or_404(summary_id, owner_id)
        if s.status not in ("queued", "processing"):
            raise SummaryStateError(f"Cannot cancel a '{s.status}' summary.")
        s.status = "cancelled"
        s.stage = "cancelled"
        return self.repo.save(s)

    def reset_for_regenerate(self, summary_id: str, owner_id: str) -> Summary:
        """Reset a summary back to queued (new version) so the runner can re-run it."""
        s = self._get_or_404(summary_id, owner_id)
        self.repo.clear_sections(s.id)
        s.status = "queued"
        s.stage = "queued"
        s.progress = 0
        s.error = None
        s.section_count = 0
        s.version += 1
        return self.repo.save(s)

    def duplicate(self, summary_id: str, owner_id: str) -> Summary:
        src = self._get_or_404(summary_id, owner_id)
        copy = self.repo.create(Summary(
            owner_id=owner_id, workspace_id=src.workspace_id, scope=src.scope,
            document_id=src.document_id, document_ids=src.document_ids,
            title=validation.validate_title(f"{src.title} (copy)", default=src.title),
            summary_type=src.summary_type, language=src.language,
            status=src.status, progress=src.progress, stage=src.stage,
            model_name=src.model_name, prompt_version=src.prompt_version,
            token_usage=src.token_usage, generation_ms=src.generation_ms,
            section_count=src.section_count, parent_summary_id=src.id,
        ))
        for sec in self.repo.sections(src.id):
            cmap = self.repo.citations_for([sec.id]).get(sec.id, [])
            self.repo.add_section(
                SummarySection(summary_id=copy.id, heading=sec.heading, order=sec.order,
                                content=sec.content, citation_count=sec.citation_count),
                [SummaryCitation(
                    summary_section_id="",  # set below after section id exists
                    document_id=c.document_id, chunk_id=c.chunk_id, page_number=c.page_number,
                    workspace_id=c.workspace_id, citation_text=c.citation_text, confidence=c.confidence,
                ) for c in cmap],
            )
        self._bump_ws(copy.workspace_id, owner_id, +1)
        return copy

    def delete(self, summary_id: str, owner_id: str, *, permanent: bool = False) -> None:
        s = self._get_or_404(summary_id, owner_id)
        if permanent:
            self.repo.hard_delete(s)
        else:
            self.repo.soft_delete(s)
        self._bump_ws(s.workspace_id, s.owner_id, -1)

    # ------------------------------------------------------------------ queries
    def get(self, summary_id: str, owner_id: str) -> Summary:
        return self._get_or_404(summary_id, owner_id)

    def get_with_sections(self, summary_id: str, owner_id: str):
        s = self._get_or_404(summary_id, owner_id)
        sections = self.repo.sections(s.id)
        cits = self.repo.citations_for([sec.id for sec in sections])
        return s, sections, cits

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        summary_type: Optional[str] = None,
        status: StatusFilter = StatusFilter.any,
        document_id: Optional[str] = None,
        sort_by: SortField = SortField.created_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Summary], int]:
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        return self.repo.list(
            owner_id, workspace_id, page=page, page_size=page_size, search=search,
            summary_type=summary_type, status=status, document_id=document_id,
            sort_by=sort_by, order=order,
        )
