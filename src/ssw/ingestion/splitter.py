"""文本切分：递归字符切分。

PRD 第一阶段方案：chunk_size 500-800 中文字符，overlap 60，分隔优先级
标题→段落→句号→换行→字符。第二阶段会增加标题切分和语义切分。
"""

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ssw.config import CHUNK_SIZE, CHUNK_OVERLAP


def _build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # 中文场景下默认分隔符过于偏英文，这里加入中文标点；空串作为兜底
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )


def split(documents: list[Document]) -> list[Document]:
    """切分并补齐 chunk 级 metadata。"""
    splitter = _build_splitter()
    chunks = splitter.split_documents(documents)

    for index, chunk in enumerate(chunks):
        # chunk_index 用于排序与定位；chunk_hash 给后续增量索引比对
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_hash"] = hashlib.md5(
            chunk.page_content.encode("utf-8")
        ).hexdigest()

    return chunks
