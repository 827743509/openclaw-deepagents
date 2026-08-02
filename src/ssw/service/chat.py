from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from ssw.schemas.chat import ChatHistory, ChatMessage, ChatStreamRequest, ChatSummary


@dataclass(frozen=True)
class ChatStreamResult:
    thread_id: str
    stream: AsyncIterator[bytes]


class ChatService:
    def __init__(self, agent: Any, checkpointer: Any) -> None:
        self.agent = agent
        self.checkpointer = checkpointer

    async def create_stream(self, request: ChatStreamRequest) -> ChatStreamResult:
        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")

        thread_id = request.thread_id or uuid.uuid4().hex
        self._validate_thread_id(thread_id)

        return ChatStreamResult(
            thread_id=thread_id,
            stream=self.stream_answer(thread_id, request),
        )

    async def list_recent(self, limit: int = 10) -> list[ChatSummary]:
        normalized_limit = min(max(limit, 1), 50)
        checkpoints = await self._list_checkpoints(normalized_limit * 20)
        seen_thread_ids: set[str] = set()
        summaries: list[ChatSummary] = []

        for checkpoint in checkpoints:
            thread_id = self._extract_thread_id(getattr(checkpoint, "config", None))
            if not thread_id or thread_id in seen_thread_ids:
                continue

            seen_thread_ids.add(thread_id)
            messages = await self._get_thread_messages(thread_id)
            summaries.append(
                ChatSummary(
                    thread_id=thread_id,
                    title=self._extract_thread_title(messages),
                    message_count=len(messages),
                    last_message=messages[-1] if messages else None,
                    updated_at=self._extract_checkpoint_timestamp(checkpoint),
                )
            )
            if len(summaries) >= normalized_limit:
                break

        return summaries

    async def get_history(self, thread_id: str) -> ChatHistory:
        self._validate_thread_id(thread_id)
        config = self._config(thread_id)
        try:
            state = await self.agent.aget_state(config)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="读取会话历史失败") from exc

        values = getattr(state, "values", None)
        return ChatHistory(
            thread_id=thread_id,
            messages=self._extract_messages(values),
        )

    async def delete_chat(self, thread_id: str) -> dict[str, bool]:
        self._validate_thread_id(thread_id)
        await self.checkpointer.adelete_thread(thread_id)
        return {"deleted": True}

    async def stream_answer(self, thread_id: str, request: ChatStreamRequest) -> AsyncIterator[bytes]:
        content = request.question.strip()
        if request.context:
            content = f"{request.context.strip()}\n\n用户问题：{content}"

        try:
            async for chunk in self.agent.astream(
                {"messages": [{"role": "user", "content": content}]},
                config=self._config(thread_id),
                stream_mode=["messages", "updates"],
                subgraphs=True,
            ):
                event_name, data = self._normalize_stream_chunk(chunk)
                yield self._to_sse(event_name, data)
        except Exception as exc:
            yield self._to_sse("error", {"detail": str(exc)})

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _normalize_stream_chunk(chunk: Any) -> tuple[str, Any]:
        stream_mode = "updates"
        data = chunk

        if isinstance(chunk, tuple):
            if len(chunk) == 3:
                _, stream_mode, data = chunk
            elif len(chunk) == 2 and isinstance(chunk[0], str) and chunk[0] in {"messages", "updates"}:
                stream_mode, data = chunk
            elif len(chunk) == 2:
                stream_mode = "messages"
                data = chunk

        event_name = "messages" if stream_mode == "messages" else "updates"
        return event_name, ChatService._jsonable(data)

    @staticmethod
    def _to_sse(event_name: str, data: Any) -> bytes:
        body = json.dumps(data, ensure_ascii=False)
        return f"event: {event_name}\ndata: {body}\n\n".encode("utf-8")

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list | tuple):
            return [cls._jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return cls._jsonable(value.model_dump())
        if hasattr(value, "dict"):
            return cls._jsonable(value.dict())
        return str(value)

    @classmethod
    def _extract_messages(cls, value: Any) -> list[ChatMessage]:
        raw_messages = cls._find_messages(value)
        messages: list[ChatMessage] = []
        for raw_message in raw_messages:
            message = cls._to_chat_message(raw_message)
            if message:
                messages.append(message)
        return messages

    @classmethod
    def _find_messages(cls, value: Any) -> list[Any]:
        if isinstance(value, dict):
            if isinstance(value.get("messages"), list):
                return value["messages"]
            for key in ("values", "state", "checkpoint"):
                messages = cls._find_messages(value.get(key))
                if messages:
                    return messages
        return []

    @staticmethod
    def _to_chat_message(raw_message: Any) -> ChatMessage | None:
        if hasattr(raw_message, "model_dump"):
            raw_message = raw_message.model_dump()
        elif hasattr(raw_message, "dict"):
            raw_message = raw_message.dict()

        if not isinstance(raw_message, dict):
            return None

        raw_role = str(raw_message.get("role") or raw_message.get("type") or "").lower()
        if raw_role in {"human", "user"}:
            role = "user"
        elif raw_role in {"ai", "assistant"}:
            role = "assistant"
        else:
            return None

        content = ChatService._extract_content(raw_message.get("content"))
        if not content:
            return None
        return ChatMessage(role=role, content=content)

    @staticmethod
    def _extract_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return ""

    async def _list_checkpoints(self, limit: int) -> list[Any]:
        return [checkpoint async for checkpoint in self.checkpointer.alist(None, limit=limit)]

    async def _get_thread_messages(self, thread_id: str) -> list[ChatMessage]:
        try:
            state = await self.agent.aget_state(self._config(thread_id))
        except Exception:
            return []
        return self._extract_messages(getattr(state, "values", None))

    @staticmethod
    def _extract_thread_title(messages: list[ChatMessage]) -> str:
        for message in messages:
            if message.role != "user":
                continue
            content = message.content.strip()
            if "\n\n用户问题：" in content:
                content = content.rsplit("\n\n用户问题：", maxsplit=1)[-1].strip()
            return content or "新会话"
        return "新会话"

    @staticmethod
    def _extract_thread_id(config: Any) -> str:
        if not isinstance(config, dict):
            return ""
        configurable = config.get("configurable")
        if not isinstance(configurable, dict):
            return ""
        thread_id = configurable.get("thread_id")
        return thread_id if isinstance(thread_id, str) else ""

    @staticmethod
    def _extract_checkpoint_timestamp(checkpoint: Any) -> float:
        raw_checkpoint = getattr(checkpoint, "checkpoint", None)
        if isinstance(raw_checkpoint, dict):
            timestamp = raw_checkpoint.get("ts")
            if isinstance(timestamp, str):
                try:
                    from datetime import datetime

                    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
        return 0.0

    @staticmethod
    def _validate_thread_id(thread_id: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", thread_id):
            raise HTTPException(status_code=404, detail="会话不存在")
