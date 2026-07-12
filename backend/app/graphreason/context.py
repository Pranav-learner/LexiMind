"""Graph-aware (reasoning-aware) Context Engineering (Step 9).

Assembles the reasoning result into grounded evidence for the single PromptPackage → AnswerService
pathway: reasoning paths + inferred relationships (ranked by confidence), with confidence + explanation
metadata and preserved citations. Complements Phase-2/4/M2 context — it does not duplicate them; it
contributes a "Graph Reasoning" evidence block the agents' PromptPackage consumes.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_reasoning_context(result, *, limit: int = 16) -> Dict[str, Any]:
    citations: List[Dict[str, Any]] = []
    lines: List[str] = []
    idx = 0

    # reasoning paths (relationship chains) — most confident first
    for p in sorted(result.paths, key=lambda x: x.path_confidence, reverse=True)[:limit]:
        idx += 1
        lines.append(f"[{idx}] {p.relationship_chain}  (confidence {p.path_confidence:.0%})")
        ev = next((e.evidence[0] for e in p.edges if e.evidence), None)
        citations.append({"index": idx, "kind": "reasoning_path", "chain": p.relationship_chain,
                          "confidence": round(p.path_confidence, 4),
                          "document_id": (ev.get("document_id") if ev else None),
                          "text": (ev.get("text") if ev else p.relationship_chain)})

    infer_lines: List[str] = []
    for r in result.inferences[:limit]:
        idx += 1
        infer_lines.append(f"[{idx}] {r.source_name} indirectly {r.rel_type.replace('_', ' ')} "
                           f"{r.target_name} (via {', '.join(r.via) or 'direct chain'}; {r.confidence:.0%})")
        citations.append({"index": idx, "kind": "inferred_relationship", "text": r.derivation,
                          "rel_type": r.rel_type, "confidence": round(r.confidence, 4)})

    parts = []
    if lines:
        parts.append("Reasoning paths:\n" + "\n".join(lines))
    if infer_lines:
        parts.append("Inferred relationships:\n" + "\n".join(infer_lines))
    return {"context_text": "\n\n".join(parts), "citations": citations}
