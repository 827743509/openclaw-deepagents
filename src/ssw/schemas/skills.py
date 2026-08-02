from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_validator

SkillName = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]


class SkillBase(BaseModel):
    name: SkillName
    description: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)

    @field_validator("name", "description", "body")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class SkillCreate(SkillBase):
    pass


class SkillUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1)

    @field_validator("description", "body")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    skill_path: str
    body: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
