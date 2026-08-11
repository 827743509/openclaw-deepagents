from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ssw.api.database import routerDataBase
from ssw.api.chat import routerChat
from ssw.api.mcp import routerMcp
from ssw.api.skills import routerSkills
from ssw.agent import create_chat_agent
from ssw.config import SSW_WORKSPACE
from ssw.dependency import get_mcp_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    checkpoint_path = Path(SSW_WORKSPACE).resolve() /".checkpoint"/ "checkpoint.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(
        str(checkpoint_path)
    ) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        mcp_service = get_mcp_service()
        try:
            mcp_tools = await mcp_service.load_current_tools()
        except Exception as exc:
            print(f"MCP 工具加载失败，当前将不启用 MCP 工具：{exc}", flush=True)
            mcp_tools = []
        app.state.agent = create_chat_agent(checkpointer, mcp_tools)
        yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Thread-Id"],
)

app.include_router(routerChat)
app.include_router(routerDataBase)
app.include_router(routerMcp)
app.include_router(routerSkills)

static_dir = Path(__file__).resolve().parent / "static"
if static_dir.joinpath("index.html").is_file():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")
