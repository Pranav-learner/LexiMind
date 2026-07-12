"""Search/retrieval tools — thin wrappers over the EXISTING retrieval engines (Step 5/15).

NO second retrieval pipeline is created. Each tool delegates to a Phase-1/4/5 service and reshapes the
result into a uniform `ToolResult` (structured `output` + `context_text` for the prompt + `citations`).
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents.interfaces import ToolParam, ToolResult, ToolSpec
from app.agents.tools.base import BaseTool


def _q(ctx, args) -> str:
    return (args.get("query") or ctx.query or "").strip()


class WorkspaceSearchTool(BaseTool):
    """Reuses the Phase-4 unified multimodal retrieval (text/OCR/image/diagram/table/metadata)."""

    spec = ToolSpec(
        name="workspace_search", version="1.0", category="search",
        description="Search the workspace across text, OCR, images, diagrams, tables and metadata.",
        params=[ToolParam("query", "string", False, "Search query (defaults to the user request)."),
                ToolParam("top_k", "integer", False, "Max results (default 8).")],
        permissions=["search"], parallel_safe=True, cost_weight=1.0)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.mmretrieval.repository import RetrievalRepository
        from app.mmretrieval.schemas import SearchRequest
        from app.mmretrieval.service import MultimodalRetrievalService
        svc = MultimodalRetrievalService(RetrievalRepository(ctx.db))
        res = svc.search(ctx.owner_id, ctx.workspace_id, SearchRequest(
            query=_q(ctx, args), top_k=int(args.get("top_k", 8)), document_id=ctx.document_id, explain=False))
        results = res.get("results", [])
        lines: List[str] = []
        citations: List[Dict[str, Any]] = []
        for i, r in enumerate(results, start=1):
            lines.append(f"[{i}] ({r.get('modality')}) {r.get('title') or ''} {r.get('content', '')}".strip())
            citations.append({"index": i, "modality": r.get("modality"), "document_id": r.get("document_id"),
                              "page_number": r.get("page_number"), "text": (r.get("content") or "")[:300]})
        return self._result(output={"count": len(results), "modalities": sorted(set(r.get("modality") for r in results))},
                            context_text="\n".join(lines), citations=citations)


class TemporalSearchTool(BaseTool):
    """Reuses the Phase-5 temporal retrieval (transcript/speaker/chapter/topic/event/scene/frame)."""

    spec = ToolSpec(
        name="temporal_search", version="1.0", category="search",
        description="Search recordings by time, speaker, topic, chapter, event, scene and timestamp.",
        params=[ToolParam("query", "string", False, "Search query."),
                ToolParam("top_k", "integer", False, "Max results (default 8).")],
        permissions=["search"], parallel_safe=True, cost_weight=1.2)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.tretrieval.repository import TemporalRepository
        from app.tretrieval.schemas import TemporalSearchRequest
        from app.tretrieval.service import TemporalRetrievalService
        svc = TemporalRetrievalService(TemporalRepository(ctx.db))
        res = svc.search(ctx.owner_id, ctx.workspace_id, TemporalSearchRequest(
            query=_q(ctx, args), top_k=int(args.get("top_k", 8)), document_id=ctx.document_id,
            build_context=True, explain=False))
        results = res.get("results", [])
        # temporal retrieval already assembles a timestamp-preserving context + citations — reuse them.
        context_text = ""
        for r in results:
            context_text += f"[{r.get('timespan')}{' · ' + r.get('speaker_label') if r.get('speaker_label') else ''}] {r.get('content', '')}\n"
        return self._result(
            output={"count": len(results), "primary": res.get("primary"), "time_filter": res.get("time_filter")},
            context_text=context_text.strip(), citations=res.get("citations", []))


class UnifiedMediaSearchTool(BaseTool):
    """Reuses the Phase-5 Media AI Workspace unified search (temporal ⊕ documents)."""

    spec = ToolSpec(
        name="unified_media_search", version="1.0", category="search",
        description="Unified search across recordings (temporal) and documents/images.",
        params=[ToolParam("query", "string", False, "Search query."),
                ToolParam("top_k", "integer", False, "Max results per side (default 6).")],
        permissions=["search"], parallel_safe=True, cost_weight=1.5)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.mediaworkspace.service import MediaWorkspaceOrchestrator
        res = MediaWorkspaceOrchestrator(ctx.db).search(
            ctx.owner_id, ctx.workspace_id, _q(ctx, args), top_k=int(args.get("top_k", 6)),
            document_id=ctx.document_id)
        temporal = res.get("temporal", [])
        documents = res.get("documents", [])
        lines = [f"[T] {r.get('timespan', '')} {r.get('content', '')}" for r in temporal]
        lines += [f"[D] {r.get('title', '')} {r.get('content', '')}" for r in documents]
        return self._result(output={"temporal": len(temporal), "documents": len(documents)},
                            context_text="\n".join(lines))


class RetrieveTranscriptTool(BaseTool):
    """Reuses the Phase-5 media transcript reader (requires a document/recording scope)."""

    spec = ToolSpec(
        name="retrieve_transcript", version="1.0", category="retrieval",
        description="Fetch the transcript segments of the scoped recording.",
        params=[ToolParam("document_id", "string", False, "Recording id (defaults to the scoped document).")],
        permissions=["retrieval"], parallel_safe=True, cost_weight=0.8)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        doc_id = args.get("document_id") or ctx.document_id
        if not doc_id:
            return ToolResult(tool=self.spec.name, ok=False, error="No recording is in scope for a transcript.")
        from app.media.repository import MediaRepository
        segs = MediaRepository(ctx.db).segments_for(doc_id)
        text = "\n".join(f"[{s.start_ms // 1000}s {s.speaker_label}] {s.text}" for s in segs[:200])
        return self._result(output={"segments": len(segs), "document_id": doc_id}, context_text=text)


class QueryDashboardTool(BaseTool):
    """Reuses the Phase-3 analytics dashboard (read-only workspace knowledge stats)."""

    spec = ToolSpec(
        name="query_dashboard", version="1.0", category="analytics",
        description="Query the workspace knowledge dashboard (a section like 'knowledge' or 'documents').",
        params=[ToolParam("section", "string", False, "Dashboard section key (default 'knowledge').")],
        permissions=["analytics"], parallel_safe=True, cost_weight=0.5)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.analytics.repository import AnalyticsRepository
        from app.analytics.service import AnalyticsService
        section = args.get("section") or "knowledge"
        svc = AnalyticsService(AnalyticsRepository(ctx.db))
        data = svc.section(ctx.workspace_id, ctx.owner_id, section)
        return self._result(output={"section": section, "data": data},
                            context_text=f"Dashboard[{section}]: {data}")
