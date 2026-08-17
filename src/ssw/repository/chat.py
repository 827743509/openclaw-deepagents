from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AgentConversation:
    thread_id: str
    question: str
    updated_at: float


class ChatRepository:
    def __init__(self, conversation_collection: Any, checkpoint_collection: Any) -> None:
        self.collection = conversation_collection
        self.checkpoint_collection = checkpoint_collection

    async def create(
        self,
        thread_id: str,
        user_id: str,
        agent_name: str,
        question: str,
    ) -> None:
        now = datetime.now(UTC)
        await self.collection.insert_one(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "agent_name": agent_name,
                "question": question,
                "status": 0,
                "created_at": now,
                "updated_at": now,
            }
        )

    async def mark_available(self, thread_id: str) -> None:
        await self.collection.update_one(
            {"thread_id": thread_id},
            {
                "$set": {
                    "status": 1,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def checkpoint_exists(self, thread_id: str) -> bool:
        checkpoint = await self.checkpoint_collection.find_one(
            {"thread_id": thread_id},
            {"_id": 1},
        )
        return checkpoint is not None

    async def list_recent(
        self,
        user_id: str,
        agent_name: str,
        page: int,
        page_size: int,
    ) -> tuple[list[AgentConversation], bool]:
        offset = (page - 1) * page_size
        cursor = (
            self.collection.find(
                {
                    "user_id": user_id,
                    "agent_name": agent_name,
                    "status": 1,
                },
                {
                    "_id": 0,
                    "thread_id": 1,
                    "question": 1,
                    "created_at": 1,
                    "updated_at": 1,
                },
            )
            .sort("created_at", -1)
            .skip(offset)
            .limit(page_size + 1)
        )
        documents = await cursor.to_list(length=page_size + 1)
        has_more = len(documents) > page_size

        conversations: list[AgentConversation] = []
        for document in documents[:page_size]:
            thread_id = document.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id:
                continue
            question = document.get("question")
            conversations.append(
                AgentConversation(
                    thread_id=thread_id,
                    question=question if isinstance(question, str) else "",
                    updated_at=self._to_timestamp(
                        document.get("updated_at") or document.get("created_at")
                    ),
                )
            )
        return conversations, has_more

    async def delete(
        self,
        thread_id: str,
        user_id: str,
        agent_name: str,
    ) -> bool:
        result = await self.collection.delete_one(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "agent_name": agent_name,
            }
        )
        return result.deleted_count > 0

    @staticmethod
    def _to_timestamp(value: Any) -> float:
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return 0.0
