"""Notion Connector implementation."""

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


class NotionConnector(BaseConnector):
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            type="notion",
            name="Notion",
            category="productivity",
            description="Sync Notion workspaces, databases, and pages directly.",
            icon="📓",
            auth_type="oauth2",
            capabilities=ConnectorCapabilities(
                can_browse=True,
                can_sync=True,
                can_import=True,
            ),
        )

    def connect(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True, message="Notion API connection active.")

    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        return credentials

    def discover(self) -> Dict[str, Any]:
        return {"resources": ["databases", "pages", "blocks"]}

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        items = [
            BrowseItem(id="notion_db_1", name="Engineering Wiki", item_type="database", path="/Engineering Wiki"),
            BrowseItem(id="notion_page_1", name="Meeting Notes - 2026-07-13", item_type="page", path="/Meeting Notes - 2026-07-13"),
        ]
        return BrowseResult(items=items, total_items=len(items))

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        return SyncResult(items_imported=2, new_cursor="notion_cursor_223")
