"""Agent memory abstraction (Step 9) — the working/execution/scratchpad seam.

Deliberately NOT long-term semantic memory (that is Phase 7). This is a per-run, in-process store
with named scopes so tools + the runtime can share intermediate state without globals:

- `working`      — the runtime's live plan/tool bookkeeping for this run.
- `execution`    — accumulated tool outputs (the evidence the prompt is built from).
- `scratchpad`   — free space for a tool/planner to stash intermediate notes.
- `conversation` — a read view of prior conversation turns (populated by the runtime if scoped to one).
- `workspace`    — a read view of coarse workspace context (counts/scope).

`MemoryManager` implements the `MemoryStore` protocol. The scopes are fixed strings so a future
persistent/semantic backend can implement the SAME interface and swap in transparently.
"""

from __future__ import annotations

from typing import Any, Dict, List

SCOPES = ("working", "execution", "scratchpad", "conversation", "workspace")


class MemoryManager:
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {s: {} for s in SCOPES}

    def put(self, scope: str, key: str, value: Any) -> None:
        self._store.setdefault(scope, {})[key] = value

    def get(self, scope: str, key: str, default: Any = None) -> Any:
        return self._store.get(scope, {}).get(key, default)

    def scope(self, scope: str) -> Dict[str, Any]:
        return dict(self._store.get(scope, {}))

    # --- execution memory helpers (the tool-output evidence store) ---
    def record_tool(self, node_id: str, result: Any) -> None:
        self._store["execution"][node_id] = result

    def tool_outputs(self) -> List[Any]:
        return list(self._store["execution"].values())

    def snapshot(self) -> Dict[str, Any]:
        """Non-business snapshot (keys only per scope) for the debug panel."""
        return {s: sorted(list(self._store.get(s, {}).keys())) for s in SCOPES}
