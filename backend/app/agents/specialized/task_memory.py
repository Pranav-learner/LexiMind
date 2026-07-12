"""Agent task memory (Step 8) — extends the Module-1 working/execution/scratchpad memory with the
task-scoped scopes a multi-step worker needs, WITHOUT introducing long-term semantic memory (Phase 7).

`TaskMemory` reuses `MemoryManager` (same `MemoryStore` protocol) and adds:
- `evidence`      — the ranked evidence cache (so the writing phase reuses the research phase's
                    retrieval instead of searching again — Step 14 "avoid repeated retrieval").
- `results`       — intermediate phase outputs (research report → writing input, etc.).
- `agent_notes`   — free-form scratch the agent writes while reasoning.
- `workspace`/`conversation` — coarse read context (inherited scopes).

It is per-task and in-process; a persistent/semantic backend can implement the same interface later.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.memory import MemoryManager

TASK_SCOPES = ("evidence", "results", "agent_notes")


class TaskMemory(MemoryManager):
    def __init__(self):
        super().__init__()
        for s in TASK_SCOPES:
            self._store.setdefault(s, {})

    # --- evidence cache ----------------------------------------------------
    def cache_evidence(self, query_key: str, evidence: List[Any]) -> None:
        self._store["evidence"][query_key] = evidence

    def cached_evidence(self, query_key: str) -> Optional[List[Any]]:
        return self._store["evidence"].get(query_key)

    def all_evidence(self) -> List[Any]:
        out: List[Any] = []
        for group in self._store["evidence"].values():
            out.extend(group)
        return out

    # --- intermediate results ---------------------------------------------
    def put_result(self, key: str, value: Any) -> None:
        self._store["results"][key] = value

    def get_result(self, key: str, default: Any = None) -> Any:
        return self._store["results"].get(key, default)

    # --- agent notes -------------------------------------------------------
    def note(self, text: str) -> None:
        notes: List[str] = self._store["agent_notes"].setdefault("log", [])
        notes.append(text)

    def notes(self) -> List[str]:
        return list(self._store["agent_notes"].get("log", []))

    def snapshot(self) -> Dict[str, Any]:
        snap = super().snapshot()
        snap["evidence_keys"] = sorted(self._store["evidence"].keys())
        snap["result_keys"] = sorted(self._store["results"].keys())
        snap["note_count"] = len(self.notes())
        return snap
