from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ssw.dependency import get_chat_service
from ssw.schemas.chat import ChatHistory, ChatStreamRequest, ChatSummary
from ssw.service.chat import ChatService

routerChat = APIRouter(prefix="/chat", tags=["对话"])
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@routerChat.get("", response_model=list[ChatSummary])
async def list_recent_chats(
    service: ChatServiceDep,
    limit: int = 10,
) -> list[ChatSummary]:
    return await service.list_recent(limit)


@routerChat.post("/stream")
async def stream_chat_answer(
    request: ChatStreamRequest,
    service: ChatServiceDep,
) -> StreamingResponse:
    result = await service.create_stream(request)
    return StreamingResponse(
        result.stream,
        media_type="text/event-stream; charset=utf-8",
        headers={"X-Thread-Id": result.thread_id},
    )


@routerChat.get("/{thread_id}/history", response_model=ChatHistory)
async def get_chat_history(thread_id: str, service: ChatServiceDep) -> ChatHistory:
    return await service.get_history(thread_id)


@routerChat.delete("/{thread_id}")
async def delete_chat(thread_id: str, service: ChatServiceDep) -> dict[str, bool]:
    return await service.delete_chat(thread_id)
