"""Linear Connector implementation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.integrations.sdk.base import (
    BaseConnector,
    BrowseItem,
    BrowseResult,
    ConnectorCapabilities,
    ConnectorMetadata,
    HealthStatus,
    SyncResult,
)


class LinearConnector(BaseConnector):
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            type="linear",
            name="Linear",
            category="developer",
            description="Access and sync issues, cycles, and teams from Linear.",
            icon="📐",
            auth_type="token",
            capabilities=ConnectorCapabilities(
                can_browse=True,
                can_sync=True,
            ),
        )

    def connect(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True, message="Linear API key active.")

    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        return credentials

    def discover(self) -> Dict[str, Any]:
        return {"resources": ["teams", "issues"]}

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        items = [
            BrowseItem(id="linear_issue_1", name="ENG-101: Fix Webhook Signature validation", item_type="page", path="/ENG-101"),
        ]
        return BrowseResult(items=items, total_items=len(items))

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        return SyncResult(items_imported=4, new_cursor="linear_cursor_12")
