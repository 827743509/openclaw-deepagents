import os
from functools import lru_cache
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from ssw.config import SSW_API_KEY, SSW_BASE_URL, SSW_MODEL


@lru_cache(maxsize=1)
def build_llm() -> ChatOpenAI:
    api_key = SSW_API_KEY or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("缺少模型 API Key，请在 .env 中配置 SSW_API_KEY 或 OPENAI_API_KEY")

    os.environ.setdefault("OPENAI_API_KEY", api_key)
    return ChatOpenAI(
        model=SSW_MODEL,
        api_key=api_key,
        base_url=SSW_BASE_URL,
        stream_usage=True,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )


TRAVEL_MCP_CONNECTIONS = {
    "ssw": {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:8080/ssw-mcp-server/mcp",
    },
}


_mcp_tools_cache: dict[str, list[Any]] = {}


async def load_mcp_tools_by_name(name: str) -> list[Any]:
    if name in _mcp_tools_cache:
        return _mcp_tools_cache[name]

    if name not in TRAVEL_MCP_CONNECTIONS:
        raise ValueError(f"Unknown MCP connection: {name}")

    client = MultiServerMCPClient({
        name: TRAVEL_MCP_CONNECTIONS[name],
    })

    tools = await client.get_tools()
    _mcp_tools_cache[name] = tools
    return tools
