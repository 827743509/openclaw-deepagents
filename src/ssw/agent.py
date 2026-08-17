from __future__ import annotations
from pathlib import Path
from typing import Any
from deepagents.backends import LocalShellBackend, CompositeBackend, StoreBackend
from langchain.agents.middleware import ToolCallLimitMiddleware
from ssw.llm import build_llm
from deepagents import (
    create_deep_agent,
)
from ssw.config import SSW_WORKSPACE, AGENT_NAME
from ssw.middleware.DynamicSkillMiddleware import DynamicSkillsMiddleware
from ssw.middleware.DynamicToolMiddleware import DynamicToolMiddleware
from ssw.middleware.permission_approval_middleware import PermissionApprovalMiddleware
from ssw.subagents.text_to_sql import text_to_sql_subagent

SYSTEM_PROMPT = """
      你是一个企业级多功能智能体（Multi-Agent Assistant），负责理解用户需求、规划任务、选择合适技能并完成复杂工作。
      你的核心职责：
      1. 理解用户意图
      2. 分析任务类型
      3. 选择最合适的技能（Skill）
      4. 调用工具完成任务
      你具有长期记忆能力。
      当用户明确要求“记住”、“以后记得”、“保存这个偏好”，
      或者出现对未来对话有长期价值的信息时，
      将信息写入 /memories/AGENTS.md。
      需要读取用户长期信息时，优先读取 /memories/AGENTS.md。
      更新已有信息时优先使用 edit_file，
      不要无意义地重复追加相同内容。
    """

workspace = Path(SSW_WORKSPACE).resolve()
SKILLS_PATH = workspace / "skills/main"
SKILLS_PATH.mkdir(parents=True, exist_ok=True)

subagents = [
    text_to_sql_subagent,
]

llm =build_llm()



def create_chat_agent(checkpoint: Any,redis_store, tools: list[Any] | None = None):
    return  create_deep_agent(
    model=llm,
    tools=tools or [],
    middleware=[
        DynamicSkillsMiddleware(),
        PermissionApprovalMiddleware(),
        DynamicToolMiddleware(),
        ToolCallLimitMiddleware(run_limit=10),
    ],
    system_prompt=SYSTEM_PROMPT,
    skills=[str(SKILLS_PATH)],
    subagents=subagents,
    interrupt_on={
    },
    checkpointer=checkpoint,
    backend=CompositeBackend(
            # 默认路径仍然走本地文件系统
        default=LocalShellBackend(
                root_dir=str(workspace),
                virtual_mode=True,
        ),
        # 只有 /memories/ 路径走 Redis
        routes={
            "/memories/": StoreBackend(
                store=redis_store,
                namespace=lambda rt: (
                    rt.context["user_id"]
                ),
            ),
        },
    ),
    store=redis_store,
    name=AGENT_NAME,
)



