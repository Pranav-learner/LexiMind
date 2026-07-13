"""Local Filesystem Connector implementation."""

from __future__ import annotations

import os
from pathlib import Path
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


class LocalFSConnector(BaseConnector):
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            type="local_fs",
            name="Local Filesystem",
            category="storage",
            description="Sync directories from the host machine's local storage.",
            icon="🖥️",
            auth_type="none",
            capabilities=ConnectorCapabilities(
                can_browse=True,
                can_upload=True,
                can_download=True,
                can_sync=True,
            ),
        )

    def connect(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> bool:
        self.root_dir = config.get("root_dir", "/tmp")
        return True

    def disconnect(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        if os.path.exists(self.root_dir):
            return HealthStatus(healthy=True, message=f"Directory '{self.root_dir}' exists.")
        return HealthStatus(healthy=False, message=f"Directory '{self.root_dir}' not found.")

    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def discover(self) -> Dict[str, Any]:
        return {"resources": ["directories", "files"]}

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        items = [
            BrowseItem(id="local_file_1", name="local_notes.md", item_type="file", path="/local_notes.md", size_bytes=4200),
        ]
        return BrowseResult(items=items, total_items=len(items))

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        return SyncResult(items_imported=1, new_cursor="local_cursor_001")
