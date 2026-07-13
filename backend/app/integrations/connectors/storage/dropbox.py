"""Dropbox Connector implementation."""

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


class DropboxConnector(BaseConnector):
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            type="dropbox",
            name="Dropbox",
            category="storage",
            description="Integrate Dropbox shared folders and file sync workflows.",
            icon="📦",
            auth_type="oauth2",
            capabilities=ConnectorCapabilities(
                can_browse=True,
                can_upload=True,
                can_download=True,
                can_sync=True,
            ),
        )

    def connect(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True, message="Dropbox token is active.")

    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        return credentials

    def discover(self) -> Dict[str, Any]:
        return {"resources": ["files", "folders"]}

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        items = [
            BrowseItem(id="db_folder_1", name="Photos", item_type="folder", path="/Photos"),
            BrowseItem(id="db_file_1", name="Notes.txt", item_type="file", path="/Notes.txt", size_bytes=1200),
        ]
        return BrowseResult(items=items, total_items=len(items))

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        return SyncResult(items_imported=1, new_cursor="db_cursor_456")
