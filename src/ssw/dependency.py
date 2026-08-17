from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from ssw.config import AGENT_NAME, SSW_WORKSPACE
from ssw.core.MongodbClient import async_mongo_client
from ssw.repository.chat import ChatRepository
from ssw.repository.mcp import McpRepository
from ssw.repository.skills import SkillRepository
from ssw.service.chat import ChatService
from ssw.service.mcp import McpService
from ssw.service.skills import SkillService


def get_chat_service(request: Request) -> ChatService:
    return ChatService(
        agent=request.app.state.agent,
        checkpointer=request.app.state.checkpointer,
        repository=get_chat_repository(),
        user_id=request.state.user_id,
        agent_name=AGENT_NAME,
    )


@lru_cache
def get_chat_repository() -> ChatRepository:
    database = async_mongo_client["langgraph"]
    return ChatRepository(
        conversation_collection=database["agent_conversations"],
        checkpoint_collection=database["checkpoints"],
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
