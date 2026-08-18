from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from setuptools import build_meta as _setuptools_backend


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIST_DIR = WEB_DIR / "dist"
STATIC_DIR = PROJECT_ROOT / "src" / "ssw" / "static"
BUILD_HASH_FILE = STATIC_DIR / "build-source.hash"
DEFAULT_WORKSPACE_DIR = PROJECT_ROOT / "src" / "ssw" / "default_workspace"
PACKAGE_LANGGRAPH_CONFIG = PROJECT_ROOT / "src" / "ssw" / "langgraph.json"
SOURCE_LANGGRAPH_CONFIG = PROJECT_ROOT / "langgraph.build.json"
PACKAGE_ENV_FILE = PROJECT_ROOT / "src" / "ssw" / ".env.dev"
SOURCE_PACKAGE_ENV_FILE = PROJECT_ROOT / ".env.dev"
DEFAULT_MCP_CONFIG = PROJECT_ROOT / "mcp.json"
DEFAULT_MAIN_SKILLS_DIR = PROJECT_ROOT / "skills" / "main"


def _frontend_source_files() -> list[Path]:
    config_files = [
        WEB_DIR / "index.html",
        WEB_DIR / "package.json",
        WEB_DIR / "package-lock.json",
        WEB_DIR / "tsconfig.json",
        WEB_DIR / "vite.config.ts",
    ]
    source_files = sorted(
        (path for path in (WEB_DIR / "src").rglob("*") if path.is_file()),
        key=lambda path: path.as_posix(),
    )
    files = [*config_files, *source_files]
    missing_files = [path for path in files if not path.is_file()]
    if missing_files:
        missing_text = "、".join(str(path) for path in missing_files)
        raise RuntimeError(f"前端构建文件缺失：{missing_text}")
    return files


def _frontend_source_hash() -> str:
    digest = hashlib.sha256()
    for path in _frontend_source_files():
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for name, value in sorted(os.environ.items()):
        if not name.startswith("VITE_"):
            continue
        digest.update(name.encode("utf-8"))
        digest.update(b"=")
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _frontend_is_current(source_hash: str) -> bool:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file() or not BUILD_HASH_FILE.is_file():
        return False
    return BUILD_HASH_FILE.read_text(encoding="utf-8").strip() == source_hash


def _find_npm() -> str:
    npm_command = os.environ.get("NPM", "npm")
    npm_path = shutil.which(npm_command)
    if npm_path is None:
        raise RuntimeError(
            "构建前端需要 Node.js/npm，请安装 Node.js 18 或更高版本后重试。"
        )
    return npm_path


def _build_frontend() -> None:
    source_hash = _frontend_source_hash()
    if _frontend_is_current(source_hash):
        print("前端资源未发生变化，复用已有构建产物。", flush=True)
        return

    npm_path = _find_npm()
    print("正在安装前端锁定依赖……", flush=True)
    subprocess.run([npm_path, "ci"], cwd=WEB_DIR, check=True)

    print("正在构建 Vue 前端……", flush=True)
    subprocess.run([npm_path, "run", "build"], cwd=WEB_DIR, check=True)

    web_index_path = WEB_DIST_DIR / "index.html"
    if not web_index_path.is_file():
        raise RuntimeError(f"前端构建完成，但未找到入口文件：{web_index_path}")

    if STATIC_DIR.exists():
        shutil.rmtree(STATIC_DIR)
    shutil.copytree(WEB_DIST_DIR, STATIC_DIR)
    BUILD_HASH_FILE.write_text(source_hash, encoding="utf-8")
    print(f"前端资源已写入：{STATIC_DIR}", flush=True)


def _package_graph_spec(graph_spec: str) -> str:
    graph_path, separator, graph_name = graph_spec.rpartition(":")
    if not separator or not graph_path.startswith("src/") or not graph_path.endswith(".py"):
        raise RuntimeError(f"无法转换 LangGraph 图路径：{graph_spec}")
    module_name = graph_path.removeprefix("src/").removesuffix(".py").replace("/", ".")
    return f"{module_name}:{graph_name}"


def _write_package_langgraph_config() -> None:
    if not SOURCE_LANGGRAPH_CONFIG.is_file():
        raise RuntimeError(f"缺少 LangGraph 配置：{SOURCE_LANGGRAPH_CONFIG}")

    source_config = json.loads(SOURCE_LANGGRAPH_CONFIG.read_text(encoding="utf-8"))
    source_graphs = source_config.get("graphs")
    if not isinstance(source_graphs, dict) or not source_graphs:
        raise RuntimeError("项目根目录的 LangGraph 配置中没有 graphs")

    package_config = {
        key: value
        for key, value in source_config.items()
        if key not in {"dependencies", "env", "graphs", "source"}
    }
    package_config["dependencies"] = ["ssw-agent"]
    package_config["graphs"] = {
        graph_id: _package_graph_spec(graph_spec)
        for graph_id, graph_spec in source_graphs.items()
    }
    PACKAGE_LANGGRAPH_CONFIG.write_text(
        json.dumps(package_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@contextmanager
def _stage_package_runtime() -> Iterator[None]:
    if not SOURCE_PACKAGE_ENV_FILE.is_file():
        raise RuntimeError(f"缺少 pip 包环境配置：{SOURCE_PACKAGE_ENV_FILE}")
    if not DEFAULT_MCP_CONFIG.is_file():
        raise RuntimeError(f"缺少默认 MCP 配置：{DEFAULT_MCP_CONFIG}")
    if not DEFAULT_MAIN_SKILLS_DIR.is_dir():
        raise RuntimeError(f"缺少默认主 Agent skills：{DEFAULT_MAIN_SKILLS_DIR}")
    if not any(DEFAULT_MAIN_SKILLS_DIR.rglob("SKILL.md")):
        raise RuntimeError(f"默认主 Agent skills 中没有 SKILL.md：{DEFAULT_MAIN_SKILLS_DIR}")

    if DEFAULT_WORKSPACE_DIR.exists():
        shutil.rmtree(DEFAULT_WORKSPACE_DIR)
    if PACKAGE_LANGGRAPH_CONFIG.exists():
        PACKAGE_LANGGRAPH_CONFIG.unlink()
    if PACKAGE_ENV_FILE.exists():
        PACKAGE_ENV_FILE.unlink()

    try:
        _write_package_langgraph_config()
        shutil.copy2(SOURCE_PACKAGE_ENV_FILE, PACKAGE_ENV_FILE)
        default_skills_dir = DEFAULT_WORKSPACE_DIR / "skills" / "main"
        default_skills_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_MCP_CONFIG, DEFAULT_WORKSPACE_DIR / "mcp.json")
        shutil.copytree(DEFAULT_MAIN_SKILLS_DIR, default_skills_dir)
        print(f"默认 workspace 资源已暂存：{DEFAULT_WORKSPACE_DIR}", flush=True)
        yield
    finally:
        if DEFAULT_WORKSPACE_DIR.exists():
            shutil.rmtree(DEFAULT_WORKSPACE_DIR)
        if PACKAGE_LANGGRAPH_CONFIG.exists():
            PACKAGE_LANGGRAPH_CONFIG.unlink()
        if PACKAGE_ENV_FILE.exists():
            PACKAGE_ENV_FILE.unlink()


def _record_digest(content: bytes) -> str:
    digest = hashlib.sha256(content).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


def _replace_exact_source_line(
    content: str,
    source_line: str,
    target_line: str,
) -> str:
    lines = content.splitlines(keepends=True)
    matching_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == source_line
    ]
    if len(matching_indexes) != 1:
        raise RuntimeError(
            "wheel 中的 start_web.py 不符合预期，"
            f"运行资源路径匹配数量为 {len(matching_indexes)}：{source_line}"
        )

    matching_index = matching_indexes[0]
    original_line = lines[matching_index]
    line_ending = original_line[len(original_line.rstrip("\r\n")) :]
    lines[matching_index] = f"{target_line}{line_ending}"
    return "".join(lines)


def _rewrite_wheel_runtime_paths(wheel_path: Path) -> None:
    temporary_wheel_path = wheel_path.with_name(f".{wheel_path.name}.tmp")
    start_web_name = "ssw/start_web.py"

    try:
        with zipfile.ZipFile(wheel_path, "r") as source_wheel:
            entries = {
                item.filename: source_wheel.read(item.filename)
                for item in source_wheel.infolist()
                if not item.is_dir()
            }

        start_web_content = entries.get(start_web_name)
        if start_web_content is None:
            raise RuntimeError(f"wheel 中缺少运行入口：{start_web_name}")
        start_web_text = start_web_content.decode("utf-8")
        start_web_text = _replace_exact_source_line(
            start_web_text,
            "PROJECT_ROOT = Path(__file__).resolve().parents[2]",
            "PROJECT_ROOT = Path(__file__).resolve().parent",
        )
        start_web_text = _replace_exact_source_line(
            start_web_text,
            "PACKAGE_DEFAULT_WORKSPACE = PROJECT_ROOT",
            'PACKAGE_DEFAULT_WORKSPACE = PROJECT_ROOT / "default_workspace"',
        )
        entries[start_web_name] = start_web_text.encode("utf-8")

        record_names = [name for name in entries if name.endswith(".dist-info/RECORD")]
        if len(record_names) != 1:
            raise RuntimeError("wheel 中缺少唯一的 RECORD 文件")
        record_name = record_names[0]
        entries.pop(record_name)

        record_stream = io.StringIO(newline="")
        record_writer = csv.writer(record_stream, lineterminator="\n")
        for name in sorted(entries):
            content = entries[name]
            record_writer.writerow((name, _record_digest(content), len(content)))
        record_writer.writerow((record_name, "", ""))
        entries[record_name] = record_stream.getvalue().encode("utf-8")

        with zipfile.ZipFile(
            temporary_wheel_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as target_wheel:
            for name, content in entries.items():
                target_wheel.writestr(name, content)
        temporary_wheel_path.replace(wheel_path)
    finally:
        if temporary_wheel_path.exists():
            temporary_wheel_path.unlink()


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    _build_frontend()
    with _stage_package_runtime():
        wheel_name = _setuptools_backend.build_wheel(
            wheel_directory,
            config_settings,
            metadata_directory,
        )
        _rewrite_wheel_runtime_paths(Path(wheel_directory) / wheel_name)
        return wheel_name


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    _build_frontend()
    with _stage_package_runtime():
        return _setuptools_backend.build_sdist(sdist_directory, config_settings)


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _setuptools_backend.build_editable(
        wheel_directory,
        config_settings,
        metadata_directory,
    )


get_requires_for_build_wheel = _setuptools_backend.get_requires_for_build_wheel
get_requires_for_build_sdist = _setuptools_backend.get_requires_for_build_sdist
get_requires_for_build_editable = _setuptools_backend.get_requires_for_build_editable
prepare_metadata_for_build_wheel = _setuptools_backend.prepare_metadata_for_build_wheel
prepare_metadata_for_build_editable = (
    _setuptools_backend.prepare_metadata_for_build_editable
)
