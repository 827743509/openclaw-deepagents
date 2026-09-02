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


LS_MONGODB_URI = os.getenv("LS_MONGODB_URI","mongodb://root:123456@localhost:27017/langgraph?authSource=admin&replicaSet=rs0")
DATABASE_URL = os.getenv("DATABASE_URL","postgresql+asyncpg://rag:rag@localhost:5432/rag_kb")

# ===== Embedding =====
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY")
EMBEDDING_BASE_URL = os.getenv(
    "EMBEDDING_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMBEDDING_DIM = _get_int_env("EMBEDDING_DIM", 1024)

EMBEDDING_BATCH_SIZE = _get_int_env("EMBEDDING_BATCH_SIZE", 10)

# ===== 文档上传与切分 =====
UPLOAD_MAX_SIZE_MB = _get_int_env("UPLOAD_MAX_SIZE_MB", 50)
CHUNK_SIZE = _get_int_env("CHUNK_SIZE", 600)
CHUNK_OVERLAP = _get_int_env("CHUNK_OVERLAP", 60)

# ===== minio =====
OSS_ORIGINS=os.getenv("OSS_ORIGINS","http://localhost:9000")
OSS_ACCESS_KEY=os.getenv("OSS_ACCESS_KEY","VRDCTCVBTVDLX0YJJHM3")
OSS_SECRET_KEY=os.getenv("OSS_SECRET_KEY","YotSomHBA5E2zPuqeqXVb65GyHWzRWEUw44aZ+Wc")
OSS_BUCKET=os.getenv("OSS_BUCKET","ssw-bucket")


CELERY_BROKER_URL=os.getenv("redis://localhost:6379/1")
CELERY_RESULT_BACKEND=os.getenv("CELERY_RESULT_BACKEND","redis://localhost:6379/2")





CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:9000",
    ).split(",")
    if origin.strip()
]
