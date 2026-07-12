"""Graph-retrieval tool (Phase 7, Module 2) — Semantic Memory as an agent retrieval provider (Step 15).

A thin wrapper over `SemanticMemoryService` so specialized agents retrieve KNOWLEDGE (entities +
relationships + neighborhoods) alongside vector/temporal retrieval — graph retrieval is just another
tool, funnelled through the same PromptPackage → AnswerService pathway. It is a cheap no-op when the
workspace has no graph yet, so enabling it everywhere adds negligible overhead.
"""

from __future__ import annotations

from typing import Any, Dict

from app.agents.interfaces import ToolParam, ToolResult, ToolSpec
from app.agents.tools.base import BaseTool


def _q(ctx, args) -> str:
    return (args.get("query") or ctx.query or "").strip()


class GraphSearchTool(BaseTool):
    """Reuses the Phase-7 semantic memory (entity recognition → traversal → graph-aware context)."""

    spec = ToolSpec(
        name="graph_search", version="1.0", category="search",
        description="Retrieve knowledge from the semantic graph: entities, relationships and neighborhoods.",
        params=[ToolParam("query", "string", False, "Search query (defaults to the user request)."),
                ToolParam("hops", "integer", False, "Traversal depth (default 2)."),
                ToolParam("top_k", "integer", False, "Max knowledge hits (default 12).")],
        permissions=["search"], parallel_safe=True, cost_weight=1.1)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.knowledge.repository import GraphRepository
        # cheap guard: no graph yet → no-op (keeps automatic agent use free)
        if GraphRepository(ctx.db).entity_count(ctx.workspace_id, ctx.owner_id) == 0:
            return self._result(output={"entities": 0, "hits": 0}, context_text="")
        from app.memory.service import SemanticMemoryService
        res = SemanticMemoryService(ctx.db).retrieve(
            ctx.workspace_id, ctx.owner_id, query=_q(ctx, args), hops=int(args.get("hops", 2)),
            limit=int(args.get("top_k", 12)), persist=False)
        return self._result(
            output={"entities": res["seed_count"], "neighborhood": res["neighborhood"]["nodes"],
                    "hits": len(res["hits"])},
            context_text=res["context_text"], citations=res["citations"])


class GraphReasonTool(BaseTool):
    """Reuses the Phase-7 M3 graph reasoner (multi-hop paths + inferred relationships + confidence)."""

    spec = ToolSpec(
        name="graph_reason", version="1.0", category="search",
        description="Reason over the knowledge graph: multi-hop paths, inferred relationships, confidence.",
        params=[ToolParam("query", "string", False, "Reasoning query (defaults to the user request)."),
                ToolParam("hops", "integer", False, "Reasoning depth (default 3).")],
        permissions=["search"], parallel_safe=True, cost_weight=1.3)

    def execute(self, ctx, args: Dict[str, Any]) -> ToolResult:
        from app.knowledge.repository import GraphRepository
        if GraphRepository(ctx.db).entity_count(ctx.workspace_id, ctx.owner_id) == 0:
            return self._result(output={"paths": 0, "inferences": 0}, context_text="")
        from app.graphreason.service import GraphReasoningService
        res = GraphReasoningService(ctx.db).reason(
            ctx.workspace_id, ctx.owner_id, query=_q(ctx, args), hops=int(args.get("hops", 3)),
            verify=False, persist=False, persist_inferences=False)
        conf = (res.get("confidence") or {}).get("overall")
        return self._result(
            output={"paths": len(res["paths"]), "inferences": len(res["inferences"]),
                    "confidence": conf, "root_causes": len(res.get("root_causes", []))},
            context_text=res["context_text"], citations=res["citations"])
