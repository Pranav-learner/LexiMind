"""Graph-aware Context Engineering (Step 9) — assemble scored graph hits into grounded evidence.

Produces the evidence a `PromptPackage` consumes, applying graph-native context engineering that
COMPLEMENTS (does not duplicate) Phase-2/4 context building:
- entity-aware deduplication  — the same node surfaced by several retrievers collapses to one hit.
- relationship-aware ranking  — hits are ordered by the memory score (which already folds edge weight).
- concept-aware compression   — capped per entity + a total budget so the block stays tight.
- graph citation preservation — every knowledge statement keeps a [n] citation with provenance.

Output is a text block + citations, ready to drop into the single PromptPackage → AnswerService pathway.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.memory.interfaces import GraphHit


def build_graph_context(hits: List[GraphHit], *, limit: int = 20) -> Dict[str, Any]:
    # entity-aware dedup: keep the highest-scoring hit per dedup key
    best: Dict[str, GraphHit] = {}
    for h in hits:
        cur = best.get(h.key)
        if cur is None or h.score > cur.score:
            best[h.key] = h
    ranked = sorted(best.values(), key=lambda h: h.score, reverse=True)[:limit]

    citations: List[Dict[str, Any]] = []
    entity_lines: List[str] = []
    rel_lines: List[str] = []
    for i, h in enumerate(ranked, start=1):
        citations.append(h.citation(i))
        line = f"[{i}] {h.text}"
        if h.kind in ("entity", "neighbor", "topic", "concept"):
            entity_lines.append(line)
        else:
            rel_lines.append(line)

    parts: List[str] = []
    if entity_lines:
        parts.append("Concepts:\n" + "\n".join(entity_lines))
    if rel_lines:
        parts.append("Relationships & evidence:\n" + "\n".join(rel_lines))
    context_text = "\n\n".join(parts)

    return {"context_text": context_text, "citations": citations,
            "hits": [h.to_dict() for h in ranked],
            "entity_count": len(entity_lines), "relationship_count": len(rel_lines)}
