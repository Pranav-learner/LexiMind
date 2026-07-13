"""BaseConnector — the universal interface every connector implements.

Future connectors plug in by subclassing ``BaseConnector`` and calling
``connector_registry.register()``. The core never imports a specific connector;
the runtime drives them through this interface.

Design mirrors the Agent ``Tool`` protocol: discover-spec → permission-gate → execute → log.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ConnectorCapabilities:
    """Declares what a connector can do — used for discovery and UI rendering."""
    can_browse: bool = False
    can_upload: bool = False
    can_download: bool = False
    can_sync: bool = False
    can_incremental_sync: bool = False
    can_import: bool = False
    can_export: bool = False
    can_bidirectional_sync: bool = False
    can_webhook: bool = False
    can_search: bool = False
    can_notify: bool = False


@dataclass
class ConnectorMetadata:
    """Static descriptor for a connector type (name, version, icon, category)."""
    type: str                 # unique key, e.g. 'google_drive'
    name: str                 # human-readable, e.g. 'Google Drive'
    category: str             # storage, productivity, developer, communication
    description: str = ""
    icon: str = "🔌"
    version: str = "1.0"
    auth_type: str = "oauth2"  # oauth2, api_key, token, basic, none
    capabilities: ConnectorCapabilities = field(default_factory=ConnectorCapabilities)
    status: str = "available"  # available, coming_soon
    docs_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type, "name": self.name, "category": self.category,
            "description": self.description, "icon": self.icon, "version": self.version,
            "auth_type": self.auth_type, "status": self.status,
            "capabilities": [k for k, v in self.capabilities.__dict__.items() if v],
        }


@dataclass
class SyncResult:
    """Result of a sync operation."""
    items_imported: int = 0
    items_exported: int = 0
    items_skipped: int = 0
    items_failed: int = 0
    new_cursor: str = ""
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class BrowseItem:
    """A single item in a browse listing."""
    id: str
    name: str
    item_type: str = "file"    # file, folder, page, issue, message, etc.
    path: str = ""
    size_bytes: int = 0
    mime_type: str = ""
    modified_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "type": self.item_type, "path": self.path,
                "size_bytes": self.size_bytes, "mime_type": self.mime_type,
                "modified_at": self.modified_at, "metadata": self.metadata}


@dataclass
class BrowseResult:
    """Result of a browse operation."""
    items: List[BrowseItem] = field(default_factory=list)
    next_cursor: str = ""
    total_items: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"items": [i.to_dict() for i in self.items],
                "next_cursor": self.next_cursor, "total_items": self.total_items}


@dataclass
class HealthStatus:
    """Connector health check result."""
    healthy: bool = True
    latency_ms: float = 0.0
    message: str = "ok"
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "healthy" if self.healthy else "unhealthy"


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for a connector."""
    requests_per_minute: int = 60
    burst_size: int = 10
    retry_after_seconds: float = 1.0


@dataclass
class RetryConfig:
    """Retry policy for connector operations."""
    max_retries: int = 3
    backoff_factor: float = 2.0
    max_backoff_seconds: float = 60.0
    retryable_status_codes: List[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])


class BaseConnector(ABC):
    """Abstract base class that every external connector must implement.

    The ``ConnectorRuntime`` calls these methods — connectors own the integration
    logic, the runtime owns retry/rate-limit/telemetry/security.
    """

    @abstractmethod
    def metadata(self) -> ConnectorMetadata:
        """Return the static descriptor for this connector type."""
        ...

    # ---- Lifecycle ----

    @abstractmethod
    def connect(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> bool:
        """Establish connection using provided config and credentials."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Release any held resources/sessions."""
        ...

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Check connector health (API reachability, token validity)."""
        ...

    # ---- Authentication ----

    @abstractmethod
    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Perform authentication. Returns credential state (tokens, expiry)."""
        ...

    def refresh_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh expired credentials. Default delegates to authenticate()."""
        return self.authenticate(credentials)

    # ---- Discovery ----

    @abstractmethod
    def discover(self) -> Dict[str, Any]:
        """Discover available resources, schemas, and capabilities."""
        ...

    # ---- Data Operations ----

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        """Browse resources at the given path."""
        return BrowseResult()

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        """Full or incremental synchronization."""
        return SyncResult()

    def upload(self, path: str, content: bytes, *, mime_type: str = "", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Upload content to the external service."""
        return {"status": "not_implemented"}

    def download(self, resource_id: str) -> bytes:
        """Download content from the external service."""
        return b""

    # ---- Webhooks ----

    def handle_webhook(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming webhook event from the external service."""
        return {"handled": False}

    # ---- Configuration ----

    def rate_limit_config(self) -> RateLimitConfig:
        """Return rate limiting configuration for this connector."""
        return RateLimitConfig()

    def retry_config(self) -> RetryConfig:
        """Return retry policy for this connector."""
        return RetryConfig()
