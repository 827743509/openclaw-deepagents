from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

src_dir = Path(__file__).resolve().parents[1]
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from ssw.api.database import routerDataBase
from ssw.api.chat import routerChat
from ssw.api.skills import routerSkills
from ssw.agent import create_chat_agent
from ssw.config import SSW_WORKSPACE


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    checkpoint_path = Path(SSW_WORKSPACE).resolve() / "checkpoint.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(
        str(checkpoint_path)
    ) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        app.state.agent = create_chat_agent(checkpointer)
        yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:9000",
        "http://localhost:9000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Thread-Id"],
)

app.include_router(routerChat)
app.include_router(routerDataBase)
app.include_router(routerSkills)
