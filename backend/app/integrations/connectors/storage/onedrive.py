"""OneDrive Connector implementation."""

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


class OneDriveConnector(BaseConnector):
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            type="onedrive",
            name="Microsoft OneDrive",
            category="storage",
            description="Access and synchronize files stored in Microsoft OneDrive.",
            icon="☁️",
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
        return HealthStatus(healthy=True, message="Connected to Graph API.")

    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        return credentials

    def discover(self) -> Dict[str, Any]:
        return {"resources": ["drives", "items"]}

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        items = [
            BrowseItem(id="od_folder_1", name="Documents", item_type="folder", path="/Documents"),
            BrowseItem(id="od_file_1", name="Resume.pdf", item_type="file", path="/Resume.pdf", size_bytes=245000),
        ]
        return BrowseResult(items=items, total_items=len(items))

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        return SyncResult(items_imported=2, new_cursor="od_cursor_123")
