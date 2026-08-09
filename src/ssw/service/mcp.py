from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from fastapi import HTTPException

from ssw.agent import create_chat_agent
from ssw.mcp_tools import load_mcp_server_tools
from ssw.repository.mcp import McpRepository
from ssw.schemas.mcp import McpApplyResult, McpConfig

ENV_PLACEHOLDER_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class McpService:
    def __init__(self, repository: McpRepository) -> None:
        self.repository = repository
        self._apply_lock = asyncio.Lock()

    async def get_config(self) -> McpConfig:
        try:
            return await asyncio.to_thread(self.repository.get)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def load_current_tools(self) -> list[Any]:
        config = await asyncio.to_thread(self.repository.get)
        return await self._load_tools(config)

    async def apply_config(
        self,
        config: McpConfig,
        checkpointer: Any,
    ) -> tuple[McpApplyResult, Any]:
        async with self._apply_lock:
            try:
                tools = await self._load_tools(config)
                agent = create_chat_agent(checkpointer, tools)
                saved_config = await asyncio.to_thread(self.repository.save, config)
            except HTTPException:
                raise
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            loaded_servers = [
                name
                for name, server in saved_config.mcp_servers.items()
                if server.is_enabled
            ]
            return (
                McpApplyResult(
                    config=saved_config,
                    loaded_servers=loaded_servers,
                    tool_count=len(tools),
                ),
                agent,
            )

    async def _load_tools(self, config: McpConfig) -> list[Any]:
        loaded_tools: list[Any] = []
        tool_sources: dict[str, str] = {}

        for server_name, server in config.mcp_servers.items():
            if not server.is_enabled:
                continue
            connection = self._resolve_environment_values(server.to_connection())
            try:
                server_tools = await load_mcp_server_tools(server_name, connection)
            except Exception as exc:
                raise ValueError(
                    f"MCP Server {server_name!r} 加载失败：{exc}"
                ) from exc

            for tool in server_tools:
                existing_server = tool_sources.get(tool.name)
                if existing_server:
                    raise ValueError(
                        f"MCP 工具名称冲突：{tool.name!r} 同时存在于 "
                        f"{existing_server!r} 和 {server_name!r}"
                    )
                tool_sources[tool.name] = server_name
                loaded_tools.append(tool)
        return loaded_tools

    def _resolve_environment_values(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._resolve_environment_values(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_environment_values(item) for item in value]
        if not isinstance(value, str):
            return value

        match = ENV_PLACEHOLDER_PATTERN.fullmatch(value)
        if not match:
            return value
        env_name = match.group(1)
        env_value = os.getenv(env_name)
        if env_value is None:
            raise ValueError(f"环境变量 {env_name} 未配置")
        return env_value
