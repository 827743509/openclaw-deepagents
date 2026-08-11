from __future__ import annotations

import asyncio
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient


async def load_mcp_server_tools(
    server_name: str,
    connection: dict[str, Any],
    timeout_seconds: float = 10,
) -> list[Any]:
    client = MultiServerMCPClient({server_name: connection})
    try:
        async with asyncio.timeout(timeout_seconds):
            tools = await client.get_tools(server_name=server_name)
    except TimeoutError as exc:
        raise TimeoutError(
            f"MCP Server {server_name!r} 加载工具超时（{timeout_seconds:g} 秒）"
        ) from exc

    for tool in tools:
        tool.metadata = {
            **(tool.metadata or {}),
            "mcpserver": server_name,
            "permissions":"high"
        }
    return tools
