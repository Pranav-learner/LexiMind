"""Graph Verification Adapter (Step 5) — REUSE the Verification Engine + graph topology checks.

Two complementary checks, no verification logic duplicated:
- graph consistency  — reuse the Module-1 `GraphValidator` over the reasoning subgraph (broken/self-loop/
                       duplicate/orphan) → a topology health signal.
- conflicting paths  — two inferred relationships between the same pair with contradictory types
                       (e.g. `depends_on` vs an antonymic relation) — a structural contradiction check.
- conclusion check   — reuse the Phase-6 `VerificationService` to verify the reasoning CONCLUSION (the
                       inferred statements) against the path EVIDENCE (feeding graph reasoning as another
                       evidence source into the same verifier).

Returns a compact report the confidence propagator + explanation consume.
"""

from __future__ import annotations

from typing import Any, Dict, List

_CONFLICT_PAIRS = {("depends_on", "part_of"): False}   # placeholder for future antonymic conflicts


class GraphVerificationAdapter:
    name = "graph-verification-v1"

    def verify(self, db, workspace_id: str, owner_id: str, *, subgraph_entities, subgraph_edges,
               inferences, paths, answer_fn=None, verify_conclusions: bool = False) -> Dict[str, Any]:
        # 1) topology consistency — reuse Module-1 GraphValidator
        from app.knowledge.validator import GraphValidator
        topo = GraphValidator().validate(list(subgraph_entities), list(subgraph_edges))

        # 2) conflicting inferences (same endpoints, incompatible inferred relation)
        by_pair: Dict[tuple, set] = {}
        for r in inferences:
            by_pair.setdefault((r.source_id, r.target_id), set()).add(r.rel_type)
        conflicts = sum(1 for types in by_pair.values() if len(types) > 1)

        report: Dict[str, Any] = {
            "graph_consistency": topo.ok, "consistency_errors": len(topo.errors),
            "consistency_warnings": len(topo.warnings), "conflicting_paths": conflicts,
            "verified_conclusions": 0, "status": "verified" if (topo.ok and conflicts == 0) else "warning",
        }

        # 3) conclusion verification — reuse the Phase-6 VerificationService (optional, evidence-grounded)
        if verify_conclusions and inferences:
            try:
                from app.reasoning.repository import VerificationRepository
                from app.reasoning.service import VerificationService
                answer_text = "\n".join(f"{r.source_name} {r.rel_type.replace('_', ' ')} {r.target_name} [{i+1}]"
                                        for i, r in enumerate(inferences[:12]))
                evidence = []
                for i, r in enumerate(inferences[:12], start=1):
                    evidence.append({"index": i, "text": r.derivation,
                                     "document_id": (r.evidence[0].get("document_id") if r.evidence else None),
                                     "score": r.confidence})
                vr = VerificationService(VerificationRepository(db)).verify(
                    workspace_id, owner_id, answer_text=answer_text, evidence=evidence, mode="fast",
                    signals={"success": True}, agent="graph_reasoner", task_type="graph_reasoning",
                    persist=False)
                report["verified_conclusions"] = vr.get("counts", {}).get("supported", 0)
                report["conclusion_confidence"] = vr.get("confidence", {}).get("overall")
                if vr.get("status") == "failed":
                    report["status"] = "warning"
            except Exception:
                pass

        # a scalar signal for the confidence propagator
        report["signal"] = 0.9 if report["status"] == "verified" else 0.55
        return report
