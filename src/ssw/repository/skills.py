from __future__ import annotations

import json
import shutil
from pathlib import Path

from ssw.schemas.skills import SkillCreate, SkillSummary, SkillUpdate


class SkillRepository:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.skills_root = self.workspace / "skills"
        self.skills_root.mkdir(parents=True, exist_ok=True)

    def skill_path(self, skill_id: str) -> Path:
        return self.skills_root / skill_id / "SKILL.md"

    def list(self) -> list[SkillSummary]:
        skills: list[SkillSummary] = []
        for skill_file in sorted(self.skills_root.glob("*/SKILL.md")):
            skill = self._read_skill(skill_file)
            if skill:
                skills.append(skill)
        return skills

    def create(self, skill: SkillCreate) -> SkillSummary | None:
        skill_dir = self.skills_root / skill.name
        if skill_dir.exists():
            raise FileExistsError("技能已存在")

        skill_dir.mkdir(parents=True, exist_ok=False)
        skill_file = self.skill_path(skill.name)
        skill_file.write_text(self._render_skill(skill), encoding="utf-8")
        return self._read_skill(skill_file, include_body=True)

    def get(self, skill_id: str) -> SkillSummary | None:
        skill_file = self.skill_path(skill_id)
        if not skill_file.exists():
            return None
        return self._read_skill(skill_file, include_body=True)

    def update(self, skill_id: str, payload: SkillUpdate) -> SkillSummary | None:
        current = self.get(skill_id)
        if not current:
            return None

        updated = SkillCreate(
            name=current.name,
            description=payload.description or current.description,
            body=payload.body or current.body or "",
        )
        skill_file = self.skill_path(skill_id)
        skill_file.write_text(self._render_skill(updated), encoding="utf-8")
        return self._read_skill(skill_file, include_body=True)

    def replace_file(self, skill_id: str, text: str) -> SkillSummary | None:
        skill_file = self.skill_path(skill_id)
        if not skill_file.exists():
            return None

        self.validate_uploaded_skill(text)
        skill_file.write_text(text.rstrip() + "\n", encoding="utf-8")
        return self._read_skill(skill_file, include_body=True)

    def exists(self, skill_id: str) -> bool:
        return self.skill_path(skill_id).exists()

    def delete(self, skill_id: str) -> bool:
        skill_dir = (self.skills_root / skill_id).resolve()
        skills_root = self.skills_root.resolve()
        if not skill_dir.is_relative_to(skills_root):
            return False
        if not self.skill_path(skill_id).exists():
            return False

        shutil.rmtree(skill_dir)
        return True

    def validate_uploaded_skill(self, text: str) -> None:
        if not text.strip():
            raise ValueError("上传的 Skill 文档不能为空")
        if not text.startswith("---") or text.find("\n---", 3) == -1:
            raise ValueError("Skill 文档必须包含 YAML frontmatter")

        root, _ = self._parse_frontmatter(text)
        if not root.get("name") or not root.get("description"):
            raise ValueError("Skill 文档 frontmatter 必须包含 name 和 description")

    def _render_skill(self, skill: SkillCreate) -> str:
        return f"""---
name: {skill.name}
description: {self._yaml_string(skill.description)}
metadata:
  kind: skill
---

{skill.body.strip()}
"""

    def _read_skill(self, skill_file: Path, include_body: bool = False) -> SkillSummary | None:
        text = skill_file.read_text(encoding="utf-8")
        root, metadata = self._parse_frontmatter(text)
        name = root.get("name")
        description = root.get("description")
        if not name or not description:
            return None

        return SkillSummary(
            id=skill_file.parent.name,
            name=name,
            description=description,
            skill_path=self._relative_skill_path(skill_file),
            body=self._skill_body(text) if include_body else None,
            metadata=metadata,
        )

    def _relative_skill_path(self, skill_file: Path) -> str:
        try:
            return str(skill_file.relative_to(self.workspace))
        except ValueError:
            return str(skill_file)

    @staticmethod
    def _yaml_string(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, str], dict[str, str]]:
        root: dict[str, str] = {}
        metadata: dict[str, str] = {}
        if not text.startswith("---"):
            return root, metadata

        end = text.find("\n---", 3)
        if end == -1:
            return root, metadata

        in_metadata = False
        for raw_line in text[3:end].splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            if line == "metadata:":
                in_metadata = True
                continue
            if not line.startswith("  "):
                in_metadata = False

            parts = line.strip().split(":", 1)
            if len(parts) != 2:
                continue

            key, value = parts
            value = SkillRepository._parse_yaml_scalar(value.strip())
            if in_metadata:
                metadata[key] = value
            else:
                root[key] = value

        return root, metadata

    @staticmethod
    def _parse_yaml_scalar(value: str) -> str:
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return value.strip('"')
            return str(parsed)
        return value

    @staticmethod
    def _skill_body(text: str) -> str:
        if not text.startswith("---"):
            return text.strip()
        end = text.find("\n---", 3)
        if end == -1:
            return text.strip()
        return text[end + len("\n---") :].strip()
