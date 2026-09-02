from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query,Request
from fastapi.responses import StreamingResponse

from ssw.core.RateLimit import rate_limit
from ssw.dependency import get_chat_service, ChatServiceDep
from ssw.schemas.chat import (
    ChatHistory,
    ChatResumeRequest,
    ChatStreamRequest,
    ChatSummaryPage,
    ChatTaskStatus,
)
from ssw.service.chat import ChatService

routerChat = APIRouter(prefix="/chat", tags=["对话"])



@routerChat.get("", response_model=ChatSummaryPage)
async def list_recent_chats(
    service: ChatServiceDep,
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=10, ge=1, le=50),
) -> ChatSummaryPage:
    return await service.list_recent(page, page_size)


@routerChat.post("/stream")
@rate_limit(5)
async def stream_chat_answer(
    http_request: Request,
    request: ChatStreamRequest,
    service: ChatServiceDep,
) -> StreamingResponse:
    request.user_id = request.user_id or http_request.state.user_id
    result = await service.create_stream(request)
    return StreamingResponse(
        result.stream,
        media_type="text/event-stream; charset=utf-8",
        headers={"X-Thread-Id": result.thread_id},
    )


@routerChat.post("/{thread_id}/resume")
async def resume_chat_answer(
    thread_id: str,
    request: ChatResumeRequest,
    service: ChatServiceDep,
) -> StreamingResponse:
    return StreamingResponse(
        service.stream_resume(thread_id, request),
        media_type="text/event-stream; charset=utf-8",
        headers={"X-Thread-Id": thread_id},
    )


@routerChat.get("/tasks/{task_id}", response_model=ChatTaskStatus)
async def get_chat_task_status(
    task_id: str,
    thread_id: str,
    service: ChatServiceDep,
) -> ChatTaskStatus:
    return await service.get_task_status(task_id, thread_id)


@routerChat.get("/{thread_id}/history", response_model=ChatHistory)
async def get_chat_history(thread_id: str, service: ChatServiceDep) -> ChatHistory:
    return await service.get_history(thread_id)


@routerChat.delete("/{thread_id}")
async def delete_chat(thread_id: str, service: ChatServiceDep) -> dict[str, bool]:
    return await service.delete_chat(thread_id)
