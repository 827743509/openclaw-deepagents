from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from ssw.dependency import get_skill_service
from ssw.schemas.skills import SkillCreate, SkillSummary, SkillUpdate
from ssw.service.skills import SkillService

routerSkills = APIRouter(prefix="/skills", tags=["技能管理"])
SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]


@routerSkills.get("", response_model=list[SkillSummary])
async def list_skills(service: SkillServiceDep) -> list[SkillSummary]:
    return await service.list_skills()


@routerSkills.post("/add", response_model=SkillSummary)
async def create_skill(skill: SkillCreate, service: SkillServiceDep) -> SkillSummary:
    return await service.create_skill(skill)


@routerSkills.get("/{skill_id}", response_model=SkillSummary)
async def get_skill(skill_id: str, service: SkillServiceDep) -> SkillSummary:
    return await service.get_skill(skill_id)


@routerSkills.put("/{skill_id}", response_model=SkillSummary)
async def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    service: SkillServiceDep,
) -> SkillSummary:
    return await service.update_skill(skill_id, payload)


@routerSkills.delete("/{skill_id}")
async def delete_skill(skill_id: str, service: SkillServiceDep) -> dict[str, bool]:
    return await service.delete_skill(skill_id)


@routerSkills.get("/{skill_id}/file")
async def download_skill(skill_id: str, service: SkillServiceDep) -> FileResponse:
    skill_file = await service.get_skill_file_path(skill_id)
    return FileResponse(
        skill_file,
        media_type="text/markdown; charset=utf-8",
        filename=f"{skill_id}-SKILL.md",
    )


@routerSkills.post("/{skill_id}/file/replace", response_model=SkillSummary)
async def replace_skill_file(
    skill_id: str,
    service: SkillServiceDep,
    file: UploadFile = File(...),
) -> SkillSummary:
    content = await file.read()
    return await service.replace_skill_file(skill_id, file.filename, content)
