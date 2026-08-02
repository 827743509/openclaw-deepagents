from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from ssw.repository.skills import SkillRepository
from ssw.schemas.skills import SkillCreate, SkillName, SkillSummary, SkillUpdate

skill_name_adapter = TypeAdapter(SkillName)


class SkillService:
    def __init__(self, repository: SkillRepository) -> None:
        self.repository = repository

    async def list_skills(self) -> list[SkillSummary]:
        return await asyncio.to_thread(self.repository.list)

    async def create_skill(self, skill: SkillCreate) -> SkillSummary:
        try:
            created = await asyncio.to_thread(self.repository.create, skill)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="技能已存在") from exc
        if not created:
            raise HTTPException(status_code=500, detail="技能创建失败")
        return created

    async def get_skill(self, skill_id: str) -> SkillSummary:
        self._validate_skill_id(skill_id)
        skill = await asyncio.to_thread(self.repository.get, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="技能不存在")
        return skill

    async def update_skill(self, skill_id: str, payload: SkillUpdate) -> SkillSummary:
        self._validate_skill_id(skill_id)
        skill = await asyncio.to_thread(self.repository.update, skill_id, payload)
        if not skill:
            raise HTTPException(status_code=404, detail="技能不存在")
        return skill

    async def delete_skill(self, skill_id: str) -> dict[str, bool]:
        self._validate_skill_id(skill_id)
        deleted = await asyncio.to_thread(self.repository.delete, skill_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="技能不存在")
        return {"deleted": True}

    async def get_skill_file_path(self, skill_id: str) -> Path:
        self._validate_skill_id(skill_id)
        exists = await asyncio.to_thread(self.repository.exists, skill_id)
        if not exists:
            raise HTTPException(status_code=404, detail="技能不存在")
        return self.repository.skill_path(skill_id)

    async def replace_skill_file(self, skill_id: str, filename: str | None, content: bytes) -> SkillSummary:
        self._validate_skill_id(skill_id)
        if filename and not filename.lower().endswith(".md"):
            raise HTTPException(status_code=400, detail="只支持上传 .md 文件")

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Skill 文档必须使用 UTF-8 编码") from exc

        try:
            skill = await asyncio.to_thread(self.repository.replace_file, skill_id, text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not skill:
            raise HTTPException(status_code=404, detail="技能不存在")
        return skill

    @staticmethod
    def _validate_skill_id(skill_id: str) -> None:
        try:
            skill_name_adapter.validate_python(skill_id)
        except ValidationError as exc:
            raise HTTPException(status_code=404, detail="技能不存在") from exc
