from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)


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
AGENT_NAME = os.getenv("AGENT_NAME","ssw-agent")
REDIS_URL = os.getenv("REDIS_URL")
SSW_WORKSPACE = str(PROJECT_ROOT)
SSW_WEB_HOST = os.getenv("SSW_WEB_HOST", "127.0.0.1")
SSW_WEB_PORT = _get_int_env("SSW_WEB_PORT", 8000)
SSW_AGENT_PROTOCOL_HOST = os.getenv("SSW_AGENT_PROTOCOL_HOST", "127.0.0.1")
SSW_AGENT_PROTOCOL_PORT = _get_int_env("SSW_AGENT_PROTOCOL_PORT", 2024)
SSW_AGENT_PROTOCOL_URL = os.getenv(
    "SSW_AGENT_PROTOCOL_URL",
    f"http://{SSW_AGENT_PROTOCOL_HOST}:{SSW_AGENT_PROTOCOL_PORT}",
)


LS_MONGODB_URI=os.getenv("LS_MONGODB_URI","mongodb://root:123456@localhost:27017/langgraph?authSource=admin&replicaSet=rs0")
