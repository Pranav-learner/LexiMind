"""Model Context Protocol (MCP) client integration.

Registers external MCP server tools dynamically into the existing ``ToolRegistry``
as standard Agent Tools. This allows the Agent Runtime and Planner to invoke
external developer tools without changing the core execution engine.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agents.interfaces import Tool, ToolParam, ToolResult, ToolSpec
from app.agents.registry import tool_registry
from app.integrations.errors import MCPServerError
from app.integrations.models import MCPServerRegistration

logger = logging.getLogger(__name__)


class MCPToolBridge:
    """Wraps an external MCP tool into the standard Agent Tool Protocol."""

    def __init__(self, server_id: str, server_url: str, mcp_tool_spec: Dict[str, Any]):
        self.server_id = server_id
        self.server_url = server_url
        self.mcp_name = mcp_tool_spec.get("name", "unknown")

        # Map MCP schema params to ToolParams
        params = []
        input_schema = mcp_tool_spec.get("inputSchema", {})
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        for p_name, p_info in properties.items():
            params.append(
                ToolParam(
                    name=p_name,
                    type=p_info.get("type", "string"),
                    required=p_name in required_fields,
                    description=p_info.get("description", ""),
                )
            )

        # Dynamic name spacing to avoid tool collisions: 'mcp_{server_id}_{mcp_name}'
        clean_server_id = server_id.replace("mcp_", "")
        self.spec = ToolSpec(
            name=f"mcp_{clean_server_id}_{self.mcp_name}",
            version="1.0",
            description=mcp_tool_spec.get("description", "External MCP tool."),
            category="general",
            params=params,
            permissions=["mcp"],
        )

    def execute(self, ctx: Any, args: Dict[str, Any]) -> ToolResult:
        """Dispatches execution to the external MCP server endpoint."""
        import httpx
        try:
            payload = {
                "method": "tools/call",
                "params": {
                    "name": self.mcp_name,
                    "arguments": args,
                }
            }
            with httpx.Client(timeout=30.0) as client:
                # Dispatches directly to the MCP server URL
                response = client.post(self.server_url, json=payload)

            if response.status_code != 200:
                return ToolResult(
                    tool=self.spec.name,
                    ok=False,
                    error=f"MCP Server returned HTTP {response.status_code}",
                )

            res_data = response.json()
            if "error" in res_data:
                return ToolResult(
                    tool=self.spec.name,
                    ok=False,
                    error=res_data["error"].get("message", "MCP Tool call failed."),
                )

            content_list = res_data.get("result", {}).get("content", [])
            text_parts = [c.get("text", "") for c in content_list if c.get("type") == "text"]
            context_text = "\n".join(text_parts)

            return ToolResult(
                tool=self.spec.name,
                ok=True,
                output=res_data.get("result", {}),
                context_text=context_text,
            )

        except Exception as e:
            return ToolResult(
                tool=self.spec.name,
                ok=False,
                error=f"MCP invocation failed: {e}",
            )


class MCPClientManager:
    """Manages MCP server discovery, tool bridging, and dynamic registry updates."""

    def __init__(self, db: Session):
        self.db = db

    def sync_server_tools(self, server_id: str) -> List[ToolSpec]:
        """Discovers tools from an MCP server and registers them in ToolRegistry."""
        server = self.db.query(MCPServerRegistration).filter(
            MCPServerRegistration.id == server_id,
            MCPServerRegistration.is_active.is_(True),
        ).first()

        if not server:
            from app.integrations.errors import MCPServerNotFound
            raise MCPServerNotFound(server_id)

        import httpx
        try:
            # Query external MCP server tools list
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    server.server_url,
                    json={"method": "tools/list", "params": {}},
                )

            if response.status_code != 200:
                raise MCPServerError(server.name, f"HTTP {response.status_code}")

            tools_list = response.json().get("result", {}).get("tools", [])
            server.discovered_tools = tools_list
            server.status = "connected"
            server.health = "healthy"
            server.last_health_check = datetime.now(timezone.utc).replace(tzinfo=None)
            self.db.commit()

            # Bridge & register each tool
            registered_specs = []
            registry = tool_registry()
            for t_spec in tools_list:
                bridge = MCPToolBridge(server_id, server.server_url, t_spec)
                registry.register(bridge)
                registered_specs.append(bridge.spec)

            return registered_specs

        except Exception as e:
            server.status = "error"
            server.health = "unhealthy"
            server.last_health_check = datetime.now(timezone.utc).replace(tzinfo=None)
            self.db.commit()
            raise MCPServerError(server.name, str(e))
