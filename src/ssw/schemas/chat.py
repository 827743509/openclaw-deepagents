from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    thread_id: str | None = None
    question: str = Field(min_length=1)
    context: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatHistory(BaseModel):
    thread_id: str
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSummary(BaseModel):
    thread_id: str
    title: str
    message_count: int
    last_message: ChatMessage | None = None
    updated_at: float
