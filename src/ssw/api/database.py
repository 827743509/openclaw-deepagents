from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from ssw.config import SSW_WORKSPACE
from ssw.llm import build_llm
routerDataBase = APIRouter(prefix="/database", tags=["数据库管理"])
workspace = Path(SSW_WORKSPACE).resolve()
DataSourceType = Literal["mysql", "clickhouse"]
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = workspace / "skills" / "text_to_sql"


class DataSourceConnection(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: DataSourceType
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(gt=0, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=512)

    @field_validator("name", "host", "database", "username")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class DataSourceCreate(DataSourceConnection):
    skill_body: str = Field(min_length=1)

    @field_validator("skill_body")
    @classmethod
    def strip_skill_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Skill 文档不能为空")
        return value


class DataSourceSummary(BaseModel):
    id: str
    name: str
    type: DataSourceType
    host: str
    port: int
    database: str
    username: str
    skill_path: str
    skill_body: str | None = None


class GeneratedSkill(BaseModel):
    skill_body: str
    table_count: int
    column_count: int


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower()).strip("_")
    return (slug or "datasource")[:64]


def _skill_dir(datasource_id: str) -> Path:
    return SKILLS_ROOT / datasource_id


def _skill_path(datasource_id: str) -> Path:
    return _skill_dir(datasource_id) / "SKILL.md"


def _validate_datasource_id(datasource_id: str) -> None:
    if not re.match(r"^[a-zA-Z0-9_-]+$", datasource_id):
        raise HTTPException(status_code=404, detail="数据源不存在")


def _unique_datasource_id(name: str) -> str:
    base = _slugify(name)
    candidate = base
    index = 2
    while _skill_path(candidate).exists():
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _datasource_type_label(datasource_type: DataSourceType) -> str:
    return "MySQL" if datasource_type == "mysql" else "ClickHouse"


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in row.items()}


def _frontmatter(datasource_id: str, datasource: DataSourceConnection) -> str:
    database_type = _datasource_type_label(datasource.type)
    description = f"{datasource.name} 数据源表结构，用于 Text to SQL 生成 {database_type} 查询 SQL。"
    return f"""---
name: {datasource_id}
description: "{_escape_yaml(description)}"
metadata:
  kind: datasource
  display_name: "{_escape_yaml(datasource.name)}"
  database_type: {database_type}
  host: "{_escape_yaml(datasource.host)}"
  port: {datasource.port}
  database: "{_escape_yaml(datasource.database)}"
  username: "{_escape_yaml(datasource.username)}"
  password: "{_escape_yaml(datasource.password)}"
---
"""


def _render_skill(datasource_id: str, datasource: DataSourceCreate) -> str:
    return f"{_frontmatter(datasource_id, datasource)}\n{datasource.skill_body.strip()}\n"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], dict[str, str]]:
    metadata: dict[str, str] = {}
    root: dict[str, str] = {}
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

        key_value = line.strip().split(":", 1)
        if len(key_value) != 2:
            continue

        key, value = key_value
        value = value.strip().strip('"')
        if in_metadata:
            metadata[key] = value
        else:
            root[key] = value

    return root, metadata


def _skill_body(text: str) -> str:
    if not text.startswith("---"):
        return text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return text.strip()
    return text[end + len("\n---") :].strip()


def _read_datasource(skill_file: Path, include_body: bool = False) -> DataSourceSummary | None:
    text = skill_file.read_text(encoding="utf-8")
    root, metadata = _parse_frontmatter(text)
    if metadata.get("kind") != "datasource":
        return None

    datasource_type = "clickhouse" if metadata.get("database_type", "").lower() == "clickhouse" else "mysql"
    try:
        skill_path = str(skill_file.relative_to(REPO_ROOT))
    except ValueError:
        skill_path = str(skill_file)

    return DataSourceSummary(
        id=skill_file.parent.name,
        name=metadata.get("display_name")
        or root.get("description", skill_file.parent.name).split(" 数据源", 1)[0].strip('"'),
        type=datasource_type,
        host=metadata.get("host", ""),
        port=int(metadata.get("port", "0") or 0),
        database=metadata.get("database", ""),
        username=metadata.get("username", ""),
        skill_path=skill_path,
        skill_body=_skill_body(text) if include_body else None,
    )


def _mysql_schema(datasource: DataSourceConnection) -> dict[str, Any]:
    import pymysql

    connection = pymysql.connect(
        host=datasource.host,
        port=datasource.port,
        user=datasource.username,
        password=datasource.password,
        database=datasource.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    table_name AS table_name,
                    table_comment AS table_comment
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (datasource.database,),
            )
            tables = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    table_name AS table_name,
                    column_name AS column_name,
                    column_type AS column_type,
                    is_nullable AS is_nullable,
                    column_key AS column_key,
                    column_default AS column_default,
                    extra AS extra,
                    column_comment AS column_comment,
                    ordinal_position AS ordinal_position
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
                """,
                (datasource.database,),
            )
            columns = cursor.fetchall()
    finally:
        connection.close()

    return {
        "tables": [_normalize_row(table) for table in tables],
        "columns": [_normalize_row(column) for column in columns],
    }


def _clickhouse_schema(datasource: DataSourceConnection) -> dict[str, Any]:
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=datasource.host,
        port=datasource.port,
        username=datasource.username,
        password=datasource.password,
        database=datasource.database,
        connect_timeout=10,
        send_receive_timeout=30,
    )

    tables_result = client.query(
        """
        SELECT name AS table_name, comment AS table_comment, engine
        FROM system.tables
        WHERE database = {database:String}
        ORDER BY name
        """,
        parameters={"database": datasource.database},
    )
    columns_result = client.query(
        """
        SELECT
            table AS table_name,
            name AS column_name,
            type AS column_type,
            default_expression AS column_default,
            comment AS column_comment,
            position AS ordinal_position
        FROM system.columns
        WHERE database = {database:String}
        ORDER BY table, position
        """,
        parameters={"database": datasource.database},
    )

    tables = [_normalize_row(dict(zip(tables_result.column_names, row))) for row in tables_result.result_rows]
    columns = [_normalize_row(dict(zip(columns_result.column_names, row))) for row in columns_result.result_rows]
    return {"tables": tables, "columns": columns}


def _format_schema_for_llm(datasource: DataSourceConnection, schema: dict[str, Any]) -> str:
    columns_by_table: dict[str, list[dict[str, Any]]] = {}
    for column in schema["columns"]:
        columns_by_table.setdefault(str(column["table_name"]), []).append(column)

    chunks = [
        f"数据源名称: {datasource.name}",
        f"数据库类型: {_datasource_type_label(datasource.type)}",
        f"Database: {datasource.database}",
        "",
        "表与字段信息:",
    ]

    for table in schema["tables"]:
        table_name = str(table["table_name"])
        table_comment = str(table.get("table_comment") or "")
        engine = table.get("engine")
        engine_text = f", engine={engine}" if engine else ""
        chunks.append(f"\n表: {table_name}{engine_text}")
        chunks.append(f"表注释: {table_comment or '无'}")
        chunks.append("字段:")
        for column in columns_by_table.get(table_name, []):
            nullable = column.get("is_nullable")
            column_key = column.get("column_key")
            extra = column.get("extra")
            details = [
                f"- {column.get('column_name')}: {column.get('column_type')}",
                f"注释={column.get('column_comment') or '无'}",
            ]
            if nullable:
                details.append(f"nullable={nullable}")
            if column_key:
                details.append(f"key={column_key}")
            if extra:
                details.append(f"extra={extra}")
            if column.get("column_default") not in (None, ""):
                details.append(f"default={column.get('column_default')}")
            chunks.append("; ".join(details))

    return "\n".join(chunks)


def _generate_skill_body_sync(datasource: DataSourceConnection) -> GeneratedSkill:
    schema = _mysql_schema(datasource) if datasource.type == "mysql" else _clickhouse_schema(datasource)
    if not schema["tables"]:
        raise HTTPException(status_code=400, detail="当前数据库没有读取到表")

    schema_text = _format_schema_for_llm(datasource, schema)
    database_type = _datasource_type_label(datasource.type)
    prompt = f"""
请根据下面的数据库表、字段、注释信息，生成一个用于 Text to SQL Agent 的 Skill Markdown 正文。

要求：
- 只输出 Markdown 正文，不要输出 YAML frontmatter。
- 使用中文。
- 包含数据源信息、表清单、每张表字段说明、可能的关联关系或使用建议。
- 明确 SQL 方言是 {database_type}。
- 不要编造未提供的表或字段。
- 内容要方便 LLM 后续根据自然语言问题生成只读 SQL。

{schema_text}
"""
    response = build_llm().invoke(prompt)
    content = getattr(response, "content", response)
    if isinstance(content, list):
        body = "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    else:
        body = str(content)

    body = body.strip()
    if not body:
        raise HTTPException(status_code=500, detail="LLM 没有返回 Skill 文档")

    return GeneratedSkill(
        skill_body=body,
        table_count=len(schema["tables"]),
        column_count=len(schema["columns"]),
    )


def _list_datasources_sync() -> list[DataSourceSummary]:
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    datasources: list[DataSourceSummary] = []
    for skill_file in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        datasource = _read_datasource(skill_file)
        if datasource:
            datasources.append(datasource)
    return datasources


def _create_datasource_sync(datasource: DataSourceCreate) -> DataSourceSummary | None:
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    datasource_id = _unique_datasource_id(datasource.name)
    skill_dir = _skill_dir(datasource_id)
    skill_dir.mkdir(parents=True, exist_ok=False)
    skill_file = _skill_path(datasource_id)
    skill_file.write_text(_render_skill(datasource_id, datasource), encoding="utf-8")
    return _read_datasource(skill_file, include_body=True)


def _get_datasource_sync(datasource_id: str) -> DataSourceSummary | None:
    skill_file = _skill_path(datasource_id)
    if not skill_file.exists():
        return None
    return _read_datasource(skill_file, include_body=True)


def _skill_file_exists_sync(datasource_id: str) -> bool:
    return _skill_path(datasource_id).exists()


def _validate_uploaded_skill(text: str) -> None:
    if not text.strip():
        raise HTTPException(status_code=400, detail="上传的 Skill 文档不能为空")
    if not text.startswith("---") or text.find("\n---", 3) == -1:
        raise HTTPException(status_code=400, detail="Skill 文档必须包含 YAML frontmatter")

    _, metadata = _parse_frontmatter(text)
    if metadata.get("kind") != "datasource":
        raise HTTPException(status_code=400, detail="Skill 文档 frontmatter 必须声明 metadata.kind=datasource")


def _replace_datasource_skill_sync(datasource_id: str, text: str) -> DataSourceSummary | None:
    skill_file = _skill_path(datasource_id)
    if not skill_file.exists():
        return None

    _validate_uploaded_skill(text)
    skill_file.write_text(text.rstrip() + "\n", encoding="utf-8")
    return _read_datasource(skill_file, include_body=True)


def _delete_datasource_sync(datasource_id: str) -> bool:
    skill_dir = _skill_dir(datasource_id).resolve()
    skills_root = SKILLS_ROOT.resolve()
    if not skill_dir.is_relative_to(skills_root):
        return False
    if not _skill_path(datasource_id).exists():
        return False

    shutil.rmtree(skill_dir)
    return True


@routerDataBase.get("/info")
async def user_info():
    return {"type": "mysql"}


@routerDataBase.get("/datasources", response_model=list[DataSourceSummary])
async def list_datasources() -> list[DataSourceSummary]:
    return await asyncio.to_thread(_list_datasources_sync)


@routerDataBase.post("/datasources/generate-schema", response_model=GeneratedSkill)
async def generate_datasource_schema(datasource: DataSourceConnection) -> GeneratedSkill:
    return await asyncio.to_thread(_generate_skill_body_sync, datasource)


@routerDataBase.post("/datasources/add", response_model=DataSourceSummary)
async def create_datasource(datasource: DataSourceCreate) -> DataSourceSummary:
    created = await asyncio.to_thread(_create_datasource_sync, datasource)
    if not created:
        raise HTTPException(status_code=500, detail="数据源技能文档创建失败")
    return created


@routerDataBase.get("/datasources/{datasource_id}", response_model=DataSourceSummary)
async def get_datasource(datasource_id: str) -> DataSourceSummary:
    _validate_datasource_id(datasource_id)

    datasource = await asyncio.to_thread(_get_datasource_sync, datasource_id)
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return datasource


@routerDataBase.delete("/datasources/{datasource_id}")
async def delete_datasource(datasource_id: str) -> dict[str, bool]:
    _validate_datasource_id(datasource_id)
    deleted = await asyncio.to_thread(_delete_datasource_sync, datasource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return {"deleted": True}


@routerDataBase.get("/datasources/{datasource_id}/skill")
async def download_datasource_skill(datasource_id: str) -> FileResponse:
    _validate_datasource_id(datasource_id)
    if not await asyncio.to_thread(_skill_file_exists_sync, datasource_id):
        raise HTTPException(status_code=404, detail="数据源不存在")

    return FileResponse(
        _skill_path(datasource_id),
        media_type="text/markdown; charset=utf-8",
        filename=f"{datasource_id}-SKILL.md",
    )


@routerDataBase.post("/datasources/{datasource_id}/skill/replace", response_model=DataSourceSummary)
async def replace_datasource_skill(
    datasource_id: str,
    file: UploadFile = File(...),
) -> DataSourceSummary:
    _validate_datasource_id(datasource_id)
    if file.filename and not file.filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="只支持上传 .md 文件")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Skill 文档必须使用 UTF-8 编码") from exc

    datasource = await asyncio.to_thread(_replace_datasource_skill_sync, datasource_id, text)
    if not datasource:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return datasource
