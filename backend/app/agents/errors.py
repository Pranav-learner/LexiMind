"""Agent framework domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class AgentError(Exception):
    status_code = 400
    code = "agent_error"


class ToolNotFound(AgentError):
    status_code = 404
    code = "tool_not_found"

    def __init__(self, name: str):
        super().__init__(f"Tool '{name}' is not registered.")


class AgentNotFound(AgentError):
    status_code = 404
    code = "agent_not_found"

    def __init__(self, name: str):
        super().__init__(f"Agent '{name}' is not registered.")


class ExecutionNotFound(AgentError):
    status_code = 404
    code = "execution_not_found"

    def __init__(self, execution_id: str):
        super().__init__(f"Agent execution '{execution_id}' was not found.")


class PermissionDenied(AgentError):
    status_code = 403
    code = "permission_denied"


class ToolValidationError(AgentError):
    status_code = 422
    code = "tool_validation_error"


class AgentStateError(AgentError):
    status_code = 409
    code = "invalid_state"


class ToolTimeout(AgentError):
    status_code = 504
    code = "tool_timeout"
