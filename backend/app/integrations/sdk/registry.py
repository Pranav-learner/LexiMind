"""Connector Registry — singleton discovery and registration of connector types.

Mirrors the ``ToolRegistry`` pattern: connectors register lazily on first access.
Future connectors drop in by implementing ``BaseConnector`` and calling
``connector_registry.register()``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from app.integrations.errors import ConnectorTypeNotFound
from app.integrations.sdk.base import BaseConnector, ConnectorMetadata


class ConnectorRegistry:
    """Process-wide registry of connector classes (not instances)."""

    def __init__(self):
        self._connectors: Dict[str, Type[BaseConnector]] = {}
        self._loaded = False

    def register(self, connector_cls: Type[BaseConnector]) -> None:
        """Register a connector class. Keyed by its metadata().type."""
        meta = connector_cls().metadata()
        self._connectors[meta.type] = connector_cls

    def _ensure_loaded(self) -> None:
        """Lazy-load built-in connectors on first access."""
        if self._loaded:
            return

        # Storage connectors
        from app.integrations.connectors.storage.google_drive import GoogleDriveConnector
        from app.integrations.connectors.storage.onedrive import OneDriveConnector
        from app.integrations.connectors.storage.dropbox import DropboxConnector
        from app.integrations.connectors.storage.s3 import S3Connector
        from app.integrations.connectors.storage.local_fs import LocalFSConnector
        from app.integrations.connectors.storage.webdav import WebDAVConnector

        # Productivity connectors
        from app.integrations.connectors.productivity.notion import NotionConnector
        from app.integrations.connectors.productivity.confluence import ConfluenceConnector
        from app.integrations.connectors.productivity.google_docs import GoogleDocsConnector
        from app.integrations.connectors.productivity.google_calendar import GoogleCalendarConnector
        from app.integrations.connectors.productivity.outlook import OutlookConnector
        from app.integrations.connectors.productivity.obsidian import ObsidianConnector

        # Developer connectors
        from app.integrations.connectors.developer.github import GitHubConnector
        from app.integrations.connectors.developer.gitlab import GitLabConnector
        from app.integrations.connectors.developer.jira import JiraConnector
        from app.integrations.connectors.developer.linear import LinearConnector
        from app.integrations.connectors.developer.azure_devops import AzureDevOpsConnector
        from app.integrations.connectors.developer.bitbucket import BitbucketConnector

        # Communication connectors
        from app.integrations.connectors.communication.slack import SlackConnector
        from app.integrations.connectors.communication.discord import DiscordConnector
        from app.integrations.connectors.communication.teams import TeamsConnector
        from app.integrations.connectors.communication.email import EmailConnector

        for cls in (
            GoogleDriveConnector, OneDriveConnector, DropboxConnector, S3Connector,
            LocalFSConnector, WebDAVConnector,
            NotionConnector, ConfluenceConnector, GoogleDocsConnector, GoogleCalendarConnector,
            OutlookConnector, ObsidianConnector,
            GitHubConnector, GitLabConnector, JiraConnector, LinearConnector,
            AzureDevOpsConnector, BitbucketConnector,
            SlackConnector, DiscordConnector, TeamsConnector, EmailConnector,
        ):
            self.register(cls)

        self._loaded = True

    def get(self, connector_type: str) -> Type[BaseConnector]:
        """Get a connector class by its type key."""
        self._ensure_loaded()
        cls = self._connectors.get(connector_type)
        if cls is None:
            raise ConnectorTypeNotFound(connector_type)
        return cls

    def has(self, connector_type: str) -> bool:
        self._ensure_loaded()
        return connector_type in self._connectors

    def all_types(self) -> List[ConnectorMetadata]:
        """Return metadata for all registered connector types."""
        self._ensure_loaded()
        return [cls().metadata() for cls in self._connectors.values()]

    def categories(self) -> Dict[str, List[ConnectorMetadata]]:
        """Group connector metadata by category."""
        result: Dict[str, List[ConnectorMetadata]] = {}
        for meta in self.all_types():
            result.setdefault(meta.category, []).append(meta)
        return result


# Process-wide singleton (connectors lazy-load on first use).
_REGISTRY: Optional[ConnectorRegistry] = None


def connector_registry() -> ConnectorRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ConnectorRegistry()
    return _REGISTRY
