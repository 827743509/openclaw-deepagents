from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient


async def load_mcp_server_tools(
    server_name: str,
    connection: dict[str, Any],
) -> list[Any]:
    client = MultiServerMCPClient({server_name: connection})
    tools = await client.get_tools(server_name=server_name)
    for tool in tools:
        tool.metadata = {
            **(tool.metadata or {}),
            "mcpserver": server_name,
            "permissions":"high"
        }
    return tools
