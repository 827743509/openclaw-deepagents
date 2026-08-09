from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ssw.dependency import get_mcp_service
from ssw.schemas.mcp import McpApplyResult, McpConfig
from ssw.service.mcp import McpService

routerMcp = APIRouter(prefix="/mcp", tags=["MCP 配置"])
McpServiceDep = Annotated[McpService, Depends(get_mcp_service)]


@routerMcp.get(
    "/config",
    response_model=McpConfig,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_mcp_config(service: McpServiceDep) -> McpConfig:
    return await service.get_config()


@routerMcp.put(
    "/config",
    response_model=McpApplyResult,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def update_mcp_config(
    config: McpConfig,
    request: Request,
    service: McpServiceDep,
) -> McpApplyResult:
    result, agent = await service.apply_config(
        config,
        request.app.state.checkpointer,
    )
    request.app.state.agent = agent
    return result
