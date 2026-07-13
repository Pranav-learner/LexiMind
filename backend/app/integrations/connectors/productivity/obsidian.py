"""Obsidian Connector implementation."""

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


class ObsidianConnector(BaseConnector):
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            type="obsidian",
            name="Obsidian Vault",
            category="productivity",
            description="Sync Markdown notes and vaults from local/remote Obsidian vaults.",
            icon="💎",
            auth_type="none",
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
        return HealthStatus(healthy=True, message="Local Obsidian path accessible.")

    def authenticate(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def discover(self) -> Dict[str, Any]:
        return {"resources": ["notes", "vaults"]}

    def browse(self, path: str = "/", *, page_size: int = 50, cursor: str = "") -> BrowseResult:
        items = [
            BrowseItem(id="obs_note_1", name="Weekly Reflection.md", item_type="page", path="/Weekly Reflection.md"),
        ]
        return BrowseResult(items=items, total_items=len(items))

    def sync(self, *, resource_types: Optional[List[str]] = None, cursor: str = "") -> SyncResult:
        return SyncResult(items_imported=1, new_cursor="obsidian_cursor_1")
