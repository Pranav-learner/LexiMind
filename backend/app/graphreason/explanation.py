"""Explainable AI — Explanation Builder (Step 8).

Composes STRUCTURED reasoning metadata from the reasoning result — reasoning paths, entity/relationship/
evidence chains, the confidence breakdown, and verification + citation summaries — plus deterministic
"why" answers. NO chain-of-thought is exposed: only the graph-grounded structure of the reasoning. Same
deterministic-explanation philosophy as the Phase-6 explanation engine.
"""

from __future__ import annotations

from typing import Any, Dict

REASONING_PATH = [
    "Entity recognition (query → canonical graph entities)",
    "Multi-hop path enumeration (weighted, cycle-protected)",
    "Relationship inference (transitive composition rules)",
    "Confidence propagation (evidence → edges → paths → conclusion)",
    "Graph verification (topology + evidence check, reused Verification Engine)",
]


class ExplanationBuilder:
    name = "structured-v1"

    def build(self, result) -> Dict[str, Any]:
        top_paths = result.paths[:5]
        return {
            "reasoning_pipeline": REASONING_PATH,
            "reasoning_paths": [p.to_dict() for p in top_paths],
            "relationship_chains": [p.relationship_chain for p in top_paths],
            "entity_chain": self._entity_chain(top_paths),
            "evidence_chain": self._evidence_chain(top_paths),
            "inferred_relationships": [r.to_dict() for r in result.inferences[:8]],
            "confidence": result.confidence.to_dict() if result.confidence is not None else None,
            "verification_summary": self._verification(result.verification),
            "citation_summary": {"count": len(result.citations),
                                 "sources": sorted({c.get("document_id") for c in result.citations
                                                    if c.get("document_id")})},
            "why_conclusion": self._why_conclusion(result),
            "why_entities": [s.get("name") for s in result.seeds],
            "why_relationships": ("Relationships were traversed by weight + confidence; inferences follow "
                                  "deterministic transitive composition rules over the extracted edges."),
        }

    @staticmethod
    def _entity_chain(paths) -> list:
        seen, chain = set(), []
        for p in paths:
            for n in p.node_names:
                if n not in seen:
                    seen.add(n); chain.append(n)
        return chain[:20]

    @staticmethod
    def _evidence_chain(paths) -> list:
        out = []
        for p in paths:
            for e in p.edges:
                for ev in e.evidence:
                    t = (ev.get("text") or "").strip()
                    if t:
                        out.append({"relationship": f"{e.source_name} —{e.rel_type}→ {e.target_name}",
                                    "text": t[:200]})
        return out[:12]

    @staticmethod
    def _verification(v) -> Dict[str, Any]:
        if not v:
            return {"status": "not_run"}
        return {"status": v.get("status"), "consistency": v.get("graph_consistency"),
                "conflicts": v.get("conflicting_paths", 0)}

    @staticmethod
    def _why_conclusion(result) -> str:
        conf = result.confidence.overall if result.confidence is not None else 0.0
        return (f"Derived from {len(result.paths)} reasoning path(s) over {len(result.seeds)} recognized "
                f"entity(ies), yielding {len(result.inferences)} inferred relationship(s) at "
                f"{conf:.0%} confidence.")
