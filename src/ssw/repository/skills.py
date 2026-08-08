from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ssw.schemas.skills import SkillCreate, SkillSummary, SkillUpdate


class SkillRepository:
    MAX_ARCHIVE_SIZE = 10 * 1024 * 1024
    MAX_EXTRACTED_SIZE = 50 * 1024 * 1024
    MAX_ARCHIVE_FILES = 500

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.skills_root = self.workspace / "skills" / "main"
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

    def import_zip(self, content: bytes) -> SkillSummary | None:
        if not content:
            raise ValueError("上传的 Skill ZIP 包不能为空")
        if len(content) > self.MAX_ARCHIVE_SIZE:
            raise ValueError("Skill ZIP 包不能超过 10 MB")

        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise ValueError("上传的文件不是有效的 ZIP 包") from exc

        staging_dir: Path | None = None
        try:
            archive_entries = self._validate_archive_entries(archive.infolist())
            skill_entries = [
                (info, parts)
                for info, parts in archive_entries
                if not info.is_dir() and parts[-1] == "SKILL.md"
            ]
            if not skill_entries:
                raise ValueError("ZIP 包中未找到 SKILL.md")
            if len(skill_entries) > 1:
                raise ValueError("一个 ZIP 包只能包含一个 Skill")

            skill_info, skill_parts = skill_entries[0]
            skill_prefix = skill_parts[:-1]
            try:
                skill_text = archive.read(skill_info).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("SKILL.md 必须使用 UTF-8 编码") from exc
            self.validate_uploaded_skill(skill_text)

            frontmatter, _ = self._parse_frontmatter(skill_text)
            skill_id = frontmatter["name"]
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", skill_id):
                raise ValueError("Skill 名称只能包含字母、数字、下划线和连字符")

            target_dir = (self.skills_root / skill_id).resolve()
            if not target_dir.is_relative_to(self.skills_root.resolve()):
                raise ValueError("Skill 名称不合法")
            if target_dir.exists():
                raise FileExistsError("技能已存在")

            staging_dir = Path(
                tempfile.mkdtemp(prefix=".skill-import-", dir=str(self.skills_root))
            ).resolve()
            staging_skill_dir = staging_dir / skill_id
            extracted_paths: set[Path] = set()
            for info, parts in archive_entries:
                if parts[: len(skill_prefix)] != skill_prefix:
                    continue
                relative_parts = parts[len(skill_prefix) :]
                if not relative_parts:
                    continue

                destination = staging_skill_dir.joinpath(*relative_parts).resolve()
                if not destination.is_relative_to(staging_skill_dir.resolve()):
                    raise ValueError("ZIP 包包含不安全的文件路径")
                if destination in extracted_paths:
                    raise ValueError("ZIP 包包含重复文件路径")
                extracted_paths.add(destination)

                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(info))

            extracted_skill_file = staging_skill_dir / "SKILL.md"
            if not extracted_skill_file.exists():
                raise ValueError("ZIP 包中的 Skill 目录结构不正确")
            self.validate_uploaded_skill(extracted_skill_file.read_text(encoding="utf-8"))

            os.replace(staging_skill_dir, target_dir)
            return self._read_skill(target_dir / "SKILL.md", include_body=True)
        except zipfile.BadZipFile as exc:
            raise ValueError("Skill ZIP 包内容已损坏") from exc
        finally:
            archive.close()
            if staging_dir and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def _validate_archive_entries(
        self,
        entries: list[zipfile.ZipInfo],
    ) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
        visible_entries: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
        total_size = 0
        for info in entries:
            raw_name = info.filename.replace("\\", "/")
            if not raw_name or raw_name.startswith("/") or "\x00" in raw_name:
                raise ValueError("ZIP 包包含不安全的文件路径")

            path = PurePosixPath(raw_name)
            parts = tuple(part for part in path.parts if part != ".")
            if (
                path.is_absolute()
                or not parts
                or any(part == ".." or ":" in part for part in parts)
            ):
                raise ValueError("ZIP 包包含不安全的文件路径")
            if parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
                continue
            if info.flag_bits & 0x1:
                raise ValueError("不支持加密的 Skill ZIP 包")

            file_mode = info.external_attr >> 16
            if file_mode and stat.S_ISLNK(file_mode):
                raise ValueError("ZIP 包不能包含符号链接")

            if not info.is_dir():
                total_size += info.file_size
            visible_entries.append((info, parts))

        if len(visible_entries) > self.MAX_ARCHIVE_FILES:
            raise ValueError("Skill ZIP 包中的文件数量不能超过 500 个")
        if total_size > self.MAX_EXTRACTED_SIZE:
            raise ValueError("Skill ZIP 包解压后不能超过 50 MB")
        return visible_entries

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
