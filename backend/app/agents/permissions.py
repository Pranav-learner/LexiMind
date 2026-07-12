"""Permission system (Step 10) — the runtime never executes an unauthorized tool.

A tool declares the permissions it requires (`ToolSpec.permissions`, e.g. `["search"]`,
`["generate","write"]`). `PermissionManager` grants a SET of permissions for a run and enforces
workspace/document scope. `allows(spec, ctx)` returns `(ok, reason)`; the runtime marks a denied
node `denied` and never calls it.

Future (declared, not implemented): user roles, enterprise RBAC, per-tool approval workflows. Those
plug in behind the same `PermissionPolicy` protocol — the runtime does not change.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.agents.interfaces import ToolSpec

# The default grant for an interactive workspace agent (read + search + generate inside the workspace).
DEFAULT_GRANTS = ("search", "retrieval", "analytics", "generate", "write")


class PermissionManager:
    def __init__(self, granted: Optional[List[str]] = None, *, allowed_tools: Optional[List[str]] = None):
        self.granted = set(granted) if granted is not None else set(DEFAULT_GRANTS)
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None

    def allows(self, spec: ToolSpec, ctx) -> Tuple[bool, str]:
        if self.allowed_tools is not None and spec.name not in self.allowed_tools:
            return False, f"tool '{spec.name}' not in the allowed-tools list"
        missing = [p for p in spec.permissions if p not in self.granted]
        if missing:
            return False, f"missing permission(s): {', '.join(missing)}"
        return True, "ok"
