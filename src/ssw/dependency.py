from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from ssw.config import SSW_WORKSPACE
from ssw.repository.mcp import McpRepository
from ssw.repository.skills import SkillRepository
from ssw.service.chat import ChatService
from ssw.service.mcp import McpService
from ssw.service.skills import SkillService


def get_chat_service(request: Request) -> ChatService:
    return ChatService(
        agent=request.app.state.agent,
        checkpointer=request.app.state.checkpointer,
    )


@lru_cache
def get_mcp_repository() -> McpRepository:
    return McpRepository(Path(SSW_WORKSPACE))


@lru_cache
def get_mcp_service() -> McpService:
    return McpService(get_mcp_repository())


@lru_cache
def get_skill_repository() -> SkillRepository:
    return SkillRepository(Path(SSW_WORKSPACE))


@lru_cache
def get_skill_service(repository: Annotated[SkillRepository, Depends(get_skill_repository)]) -> SkillService:
    return SkillService(repository)
