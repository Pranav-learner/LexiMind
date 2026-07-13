"""Centralized exception hierarchy for the Integration subsystem.

Every integration layer raises from this hierarchy so the API layer can map to
appropriate HTTP status codes and the middleware can log failures uniformly.
"""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for all integration errors."""
    status_code: int = 500
    code: str = "integration_error"

    def __init__(self, message: str = "An integration error occurred."):
        self.message = message
        super().__init__(message)


class ConnectorNotFound(IntegrationError):
    status_code = 404
    code = "connector_not_found"

    def __init__(self, connector_id: str = ""):
        super().__init__(f"Connector '{connector_id}' not found.")


class ConnectorTypeNotFound(IntegrationError):
    status_code = 404
    code = "connector_type_not_found"

    def __init__(self, connector_type: str = ""):
        super().__init__(f"Connector type '{connector_type}' is not registered.")


class ConnectorAlreadyInstalled(IntegrationError):
    status_code = 409
    code = "connector_already_installed"

    def __init__(self, connector_type: str = ""):
        super().__init__(f"Connector '{connector_type}' is already installed in this workspace.")


class AuthenticationFailed(IntegrationError):
    status_code = 401
    code = "auth_failed"

    def __init__(self, detail: str = "Authentication failed."):
        super().__init__(detail)


class SyncConflict(IntegrationError):
    status_code = 409
    code = "sync_conflict"

    def __init__(self, detail: str = "Sync conflict detected."):
        super().__init__(detail)


class SyncInProgress(IntegrationError):
    status_code = 409
    code = "sync_in_progress"

    def __init__(self, connector_id: str = ""):
        super().__init__(f"Sync already in progress for connector '{connector_id}'.")


class WebhookDeliveryFailed(IntegrationError):
    status_code = 502
    code = "webhook_delivery_failed"

    def __init__(self, endpoint: str = "", detail: str = ""):
        super().__init__(f"Webhook delivery to '{endpoint}' failed: {detail}")


class WebhookSignatureInvalid(IntegrationError):
    status_code = 401
    code = "webhook_signature_invalid"

    def __init__(self):
        super().__init__("Webhook signature validation failed.")


class AutomationError(IntegrationError):
    status_code = 500
    code = "automation_error"

    def __init__(self, detail: str = "Automation workflow error."):
        super().__init__(detail)


class WorkflowNotFound(IntegrationError):
    status_code = 404
    code = "workflow_not_found"

    def __init__(self, workflow_id: str = ""):
        super().__init__(f"Workflow '{workflow_id}' not found.")


class SchedulerError(IntegrationError):
    status_code = 500
    code = "scheduler_error"

    def __init__(self, detail: str = "Scheduler error."):
        super().__init__(detail)


class MCPServerError(IntegrationError):
    status_code = 502
    code = "mcp_server_error"

    def __init__(self, server: str = "", detail: str = ""):
        super().__init__(f"MCP server '{server}' error: {detail}")


class MCPServerNotFound(IntegrationError):
    status_code = 404
    code = "mcp_server_not_found"

    def __init__(self, server_id: str = ""):
        super().__init__(f"MCP server '{server_id}' not found.")


class RateLimitExceeded(IntegrationError):
    status_code = 429
    code = "rate_limit_exceeded"

    def __init__(self, connector: str = ""):
        super().__init__(f"Rate limit exceeded for connector '{connector}'.")
