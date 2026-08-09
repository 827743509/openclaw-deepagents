from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

McpTransport = Literal["streamable_http", "sse", "stdio"]


class McpServerConfig(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    disabled: bool | None = None
    transport: McpTransport | None = Field(
        default=None,
        validation_alias=AliasChoices("type", "transport"),
        serialization_alias="type",
    )
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_compatibility_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        enabled = normalized.pop("enabled", None)
        if "disabled" not in normalized and enabled is not None:
            normalized["disabled"] = not bool(enabled)
        return normalized

    @field_validator("url", "command")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_transport_fields(self) -> "McpServerConfig":
        transport = self.resolved_transport
        if transport in {"streamable_http", "sse"} and not self.url:
            raise ValueError(f"{transport} 类型必须配置 url")
        if transport == "stdio" and not self.command:
            raise ValueError("stdio 类型必须配置 command")
        return self

    @property
    def resolved_transport(self) -> McpTransport:
        if self.transport:
            return self.transport
        if self.command:
            return "stdio"
        if self.url:
            return "streamable_http"
        raise ValueError("必须配置 type、transport、command 或 url")

    @property
    def is_enabled(self) -> bool:
        return self.disabled is not True

    def to_connection(self) -> dict[str, Any]:
        connection = self.model_dump(
            exclude={"disabled", "transport"},
            exclude_none=True,
            exclude_defaults=True,
        )
        connection["transport"] = self.resolved_transport
        return connection


class McpConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict,
        alias="mcpServers",
    )

    @field_validator("mcp_servers")
    @classmethod
    def validate_server_names(
        cls,
        value: dict[str, McpServerConfig],
    ) -> dict[str, McpServerConfig]:
        for name in value:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
                raise ValueError(
                    f"MCP Server 名称 {name!r} 只能包含字母、数字、下划线和连字符"
                )
        return value


class McpApplyResult(BaseModel):
    config: McpConfig
    loaded_servers: list[str]
    tool_count: int
