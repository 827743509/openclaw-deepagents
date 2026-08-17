from __future__ import annotations

from typing import Literal

from langchain.agents.middleware.human_in_the_loop import Decision
from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    thread_id: str | None = None
    first_stream: bool  = False
    last_stream: bool | None = None
    user_id: str | None = None
    question: str = Field(min_length=1)
    skills: list[str] | None = None
    mcp_list: list[str] | None = None
    permissions: Literal["low", "high"] = "low"


class ChatResumeRequest(BaseModel):
    decisions: dict[str, Decision]
    skills: list[str] | None = None
    mcp_list: list[str] | None = None
    permissions: Literal["low", "high"] = "low"


class ChatTaskStatus(BaseModel):
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None


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


class ChatSummaryPage(BaseModel):
    items: list[ChatSummary] = Field(default_factory=list)
    page: int
    page_size: int
    has_more: bool
