"""Orchestration domain errors (transport-agnostic — each carries a `status_code`)."""

from __future__ import annotations


class OrchestrationError(Exception):
    status_code = 400
    code = "orchestration_error"


class OrchestrationNotFound(OrchestrationError):
    status_code = 404
    code = "orchestration_not_found"

    def __init__(self, ref: str):
        super().__init__(f"Orchestration '{ref}' was not found.")


class GovernanceError(OrchestrationError):
    status_code = 422
    code = "governance_violation"


class WorkflowNotFound(OrchestrationError):
    status_code = 404
    code = "workflow_not_found"

    def __init__(self, name: str):
        super().__init__(f"Workflow template '{name}' is not registered.")


class OrchestrationStateError(OrchestrationError):
    status_code = 409
    code = "invalid_state"
