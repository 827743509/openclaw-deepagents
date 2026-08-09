import os
from functools import lru_cache
from langchain_openai import ChatOpenAI

from ssw.config import SSW_API_KEY, SSW_BASE_URL, SSW_MODEL


@lru_cache(maxsize=1)
def build_llm() -> ChatOpenAI:
    api_key = SSW_API_KEY or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("缺少模型 API Key，请在 .env 中配置 SSW_API_KEY 或 OPENAI_API_KEY")

    os.environ.setdefault("OPENAI_API_KEY", api_key)
    return ChatOpenAI(
        model=SSW_MODEL,
        api_key=api_key,
        base_url=SSW_BASE_URL,
        stream_usage=True,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )
