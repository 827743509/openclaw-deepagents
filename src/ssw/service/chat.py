from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from langchain_core.messages import AIMessage
from langgraph_sdk import get_client

from ssw.config import SSW_AGENT_PROTOCOL_URL
from ssw.schemas.chat import (
    ChatHistory,
    ChatMessage,
    ChatStreamRequest,
    ChatSummary,
    ChatTaskStatus,
)


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
                context={
                        "request_skills":request.skills
                    },
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
                    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
        return 0.0

    async def get_task_status(
        self,
        task_id: str,
        parent_thread_id: str,
    ) -> ChatTaskStatus:
        result: str | None = None
        error: str | None = None
        try:
            async with get_client(url=SSW_AGENT_PROTOCOL_URL, api_key=None) as client:
                runs = await client.runs.list(thread_id=task_id, limit=1)
                if not runs:
                    raise HTTPException(status_code=404, detail="异步任务不存在")

                run = runs[0]
                status = str(run.get("status") or "unknown")
                if status == "success":
                    thread = await client.threads.get(thread_id=task_id)
                    result = self._extract_task_result(thread.get("values"))
                elif status == "error":
                    raw_error = run.get("error")
                    error = str(raw_error) if raw_error else "异步任务执行失败"
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="查询异步任务状态失败") from exc

        await self._update_task_checkpoint(
            parent_thread_id,
            task_id,
            run,
            result,
            error,
        )
        return ChatTaskStatus(
            task_id=task_id,
            status=status,
            result=result,
            error=error,
        )

    async def _update_task_checkpoint(
        self,
        parent_thread_id: str,
        task_id: str,
        run: dict[str, Any],
        result: str | None,
        error: str | None,
    ) -> None:
        config = self._config(parent_thread_id)
        try:
            state = await self.agent.aget_state(config)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="读取主会话任务状态失败") from exc
        print(f'stateType: {type(state)}')
        values = getattr(state, "values", None)
        async_tasks = values.get("async_tasks") if isinstance(values, dict) else None
        stored_task = async_tasks.get(task_id) if isinstance(async_tasks, dict) else None
        if not isinstance(stored_task, dict):
            raise HTTPException(status_code=404, detail="主会话未记录该异步任务")

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        status = str(run.get("status") or "unknown")
        run_id = str(run.get("run_id") or stored_task.get("run_id") or "")
        result_already_written = (
            stored_task.get("run_id") == run_id
            and stored_task.get("status")
            in {"success", "error", "cancelled", "interrupted", "timeout"}
        )
        updated_task = {
            **stored_task,
            "task_id": task_id,
            "thread_id": task_id,
            "run_id": run_id,
            "status": status,
            "last_checked_at": now,
            "last_updated_at": (
                now
                if stored_task.get("status") != status
                else stored_task.get("last_updated_at", now)
            ),
        }
        checkpoint_update: dict[str, Any] = {
            "async_tasks": {task_id: updated_task},
        }
        task_message = self._build_task_message(
            task_id,
            updated_task["run_id"],
            status,
            result,
            error,
        )
        if task_message is not None and not result_already_written:
            checkpoint_update["messages"] = [task_message]

        try:
            await self.agent.aupdate_state(
                config,
                checkpoint_update,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail="更新主会话任务状态失败") from exc

    @staticmethod
    def _build_task_message(
        task_id: str,
        run_id: str,
        status: str,
        result: str | None,
        error: str | None,
    ) -> AIMessage | None:
        if status == "success" and result:
            content = f"异步任务已完成：\n\n{result}"
        elif status == "error":
            content = f"异步任务执行失败：\n\n{error or '未返回错误详情'}"
        else:
            return None

        return AIMessage(
            id=f"async-task-result-{run_id or task_id}",
            content=content,
            additional_kwargs={
                "async_task_id": task_id,
                "async_task_run_id": run_id,
                "async_task_result": result,
                "async_task_error": error,
            },
        )

    @classmethod
    def _extract_task_result(cls, values: Any) -> str:
        messages = cls._extract_messages(values)
        for message in reversed(messages):
            if message.role == "assistant" and message.content.strip():
                return message.content.strip()
        return "异步任务已完成，但没有返回文本结果。"
