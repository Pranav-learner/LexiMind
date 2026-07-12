"""Shared Context Manager (Step 6) — the team's shared memory, so agents don't re-retrieve.

Holds each completed node's result (output + evidence + verification + produced task id) and exposes:
- `dependency_evidence(node)` — the union of evidence produced by a node's upstream dependencies, shaped
  as the `params["evidence"]` the Module-2 Writing/Comparison agents consume → they REUSE that evidence
  instead of searching again (the concrete "avoid duplicate retrieval" mechanism, Step 15).
- `all_results` / `all_evidence` / `all_verifications` — the pool the Result Aggregator merges.
- a coarse `workspace_context` cache computed once and shared to every node.

It stores structured artifacts only (no chain-of-thought). It reuses Module-2's evidence hand-off idea
rather than inventing a new retrieval cache.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.orchestration.interfaces import TaskNode


class SharedContextManager:
    def __init__(self):
        self._results: Dict[str, Any] = {}          # node_id -> AgentTaskResult
        self._workspace_context: Optional[Dict[str, Any]] = None
        self._metadata: Dict[str, Any] = {}

    # ------------------------------------------------------------------ results
    def put_result(self, node_id: str, result: Any) -> None:
        self._results[node_id] = result

    def get_result(self, node_id: str) -> Any:
        return self._results.get(node_id)

    def all_results(self) -> List[Any]:
        return list(self._results.values())

    # ------------------------------------------------------------------ evidence reuse (avoid re-retrieval)
    def dependency_evidence(self, node: TaskNode) -> List[Dict[str, Any]]:
        """Evidence from a node's completed dependencies, as dicts the specialized agents accept."""
        out: List[Dict[str, Any]] = []
        seen = set()
        for dep in node.depends_on:
            res = self._results.get(dep)
            if res is None:
                continue
            for e in getattr(res, "evidence", []) or []:
                d = e.to_dict() if hasattr(e, "to_dict") else dict(e)
                key = (d.get("document_id"), (d.get("text") or "")[:80], d.get("timespan"))
                if key in seen:
                    continue
                seen.add(key)
                # carry the citation payload so downstream citations stay valid
                d.setdefault("citation", getattr(e, "citation", None) or d)
                out.append(d)
        return out

    def all_evidence(self) -> List[Any]:
        out: List[Any] = []
        for res in self._results.values():
            out.extend(getattr(res, "evidence", []) or [])
        return out

    def all_verifications(self) -> List[Dict[str, Any]]:
        return [getattr(r, "verification", None) for r in self._results.values()
                if getattr(r, "verification", None)]

    # ------------------------------------------------------------------ coarse workspace context (once)
    def workspace_context(self, builder=None) -> Dict[str, Any]:
        if self._workspace_context is None and builder is not None:
            self._workspace_context = builder() or {}
        return self._workspace_context or {}

    def set_metadata(self, key: str, value: Any) -> None:
        self._metadata[key] = value

    def snapshot(self) -> Dict[str, Any]:
        return {"results": sorted(self._results.keys()),
                "evidence_total": len(self.all_evidence()),
                "verifications": len(self.all_verifications()),
                "metadata_keys": sorted(self._metadata.keys())}
