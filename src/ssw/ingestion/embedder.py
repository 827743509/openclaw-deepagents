"""Embedding 客户端：DashScope 走 OpenAI 兼容协议。

DashScope text-embedding-v3 单批最多 10 条，超过会 400；这里在 batch_size 上做约束，
真正的分批由 pipeline 负责，embedder 只暴露统一接口。
"""

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from ssw.config import EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM
from ssw.core.exceptions import ConfigurationError

_embeddings: Embeddings | None = None


def get_embeddings(EMBEDDING_BATCH_SIZE=None) -> Embeddings:
    global _embeddings
    if _embeddings is not None:
        return _embeddings

    if not EMBEDDING_API_KEY:
        raise ConfigurationError("Embedding API key 未配置，请在 .env 设置 EMBEDDING_API_KEY")

    _embeddings = OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=EMBEDDING_API_KEY,
        base_url=EMBEDDING_BASE_URL,
        dimensions=EMBEDDING_DIM,
        chunk_size=EMBEDDING_BATCH_SIZE,
        check_embedding_ctx_length=False,
    )
    return _embeddings
