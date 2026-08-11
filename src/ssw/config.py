from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_FILE = PROJECT_ROOT / ".env"
PACKAGE_ENV_FILE = Path(__file__).resolve().with_name(".env.dev")
ACTIVE_ENV_FILE = PACKAGE_ENV_FILE if PACKAGE_ENV_FILE.is_file() else PROJECT_ENV_FILE
load_dotenv(ACTIVE_ENV_FILE)


def _resolve_workspace() -> Path:
    configured_workspace = os.getenv("SSW_WORKSPACE")
    if not configured_workspace:
        return PROJECT_ROOT

    workspace = Path(configured_workspace).expanduser()
    if not workspace.is_absolute():
        workspace = Path.home() / workspace
    return workspace.resolve()


WORKSPACE_ROOT = _resolve_workspace()
WORKSPACE_ENV_FILE = WORKSPACE_ROOT / ".env"
if WORKSPACE_ENV_FILE != PROJECT_ENV_FILE:
    load_dotenv(WORKSPACE_ENV_FILE)


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，当前值：{raw_value}") from exc


SSW_BASE_URL = os.getenv("SSW_BASE_URL", "https://api.moonshot.cn/v1")
SSW_MODEL = os.getenv("SSW_MODEL", "kimi-k3")
SSW_API_KEY = os.getenv("SSW_API_KEY")
SSW_WORKSPACE = str(WORKSPACE_ROOT)
SSW_WEB_HOST = os.getenv("SSW_WEB_HOST", "127.0.0.1")
SSW_WEB_PORT = _get_int_env("SSW_WEB_PORT", 8000)
SSW_AGENT_PROTOCOL_HOST = os.getenv("SSW_AGENT_PROTOCOL_HOST", "127.0.0.1")
SSW_AGENT_PROTOCOL_PORT = _get_int_env("SSW_AGENT_PROTOCOL_PORT", 2024)
SSW_AGENT_PROTOCOL_URL = os.getenv(
    "SSW_AGENT_PROTOCOL_URL",
    f"http://{SSW_AGENT_PROTOCOL_HOST}:{SSW_AGENT_PROTOCOL_PORT}",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
