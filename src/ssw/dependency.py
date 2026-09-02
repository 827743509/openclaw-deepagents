from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ssw.config import AGENT_NAME, SSW_WORKSPACE
from ssw.core.MongodbClient import async_mongo_client
from ssw.db.session import get_session
from ssw.repository.chat import ChatRepository
from ssw.repository.chunk_repo import DocumentChunkRepository
from ssw.repository.document_repo import DocumentRepository
from ssw.repository.ingestion_task_repo import IngestionTaskRepository
from ssw.repository.mcp import McpRepository
from ssw.repository.skills import SkillRepository
from ssw.service.chat import ChatService
from ssw.service.document_service import DocumentService
from ssw.service.mcp import McpService
from ssw.service.skills import SkillService
from ssw.storage.file_service import FileService, get_file_service

DbSession = Annotated[AsyncSession, Depends(get_session)]
@lru_cache
def get_chat_repository() -> ChatRepository:
    database = async_mongo_client["langgraph"]
    return ChatRepository(
        conversation_collection=database["agent_conversations"],
        checkpoint_collection=database["checkpoints"],
    )


def get_chat_service(
    request: Request,
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
) -> ChatService:
    return ChatService(
        agent=request.app.state.agent,
        checkpointer=request.app.state.checkpointer,
        repository=repository,
        user_id=request.state.user_id,
        agent_name=AGENT_NAME,
    )


@lru_cache
def get_mcp_repository() -> McpRepository:
    return McpRepository(Path(SSW_WORKSPACE))


@lru_cache
def get_mcp_service(
    repository: Annotated[McpRepository, Depends(get_mcp_repository)],
) -> McpService:
    return McpService(repository)


@lru_cache
def get_skill_repository() -> SkillRepository:
    return SkillRepository(Path(SSW_WORKSPACE))


@lru_cache
def get_skill_service(repository: Annotated[SkillRepository, Depends(get_skill_repository)]) -> SkillService:
    return SkillService(repository)


def get_document_service(session:DBSessionDep,repo: Annotated[DocumentRepository, Depends(get_document_repository)],chunk_repo:Annotated[DocumentChunkRepository, Depends(get_document_chunk_repository)],task_repo:Annotated[IngestionTaskRepository, Depends(get_ingestion_task_repository)],file_service:FileServiceDep) -> DocumentService:
    return DocumentService(session,repo,chunk_repo,task_repo,file_service)

def get_document_repository(session: DbSession) -> DocumentRepository:
    return DocumentRepository(session)

def get_document_chunk_repository(session: DbSession) -> DocumentChunkRepository:
    return DocumentChunkRepository(session)

def get_ingestion_task_repository(session: DbSession) -> IngestionTaskRepository:
    return IngestionTaskRepository(session)

DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]

ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]

McpServiceDep = Annotated[McpService, Depends(get_mcp_service)]

SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]

DBSessionDep = Annotated[AsyncSession, Depends(get_session)]

FileServiceDep = Annotated[FileService, Depends(get_file_service)]