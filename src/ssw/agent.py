from __future__ import annotations
from pathlib import Path
from typing import Any
from deepagents.backends import LocalShellBackend
from langchain.agents.middleware import ToolCallLimitMiddleware

from ssw.llm import build_llm
from deepagents import (
    create_deep_agent,
)
from ssw.config import  SSW_WORKSPACE
from ssw.middleware.DynamicSkillMiddleware import DynamicSkillsMiddleware
from ssw.middleware.permission_approval_middleware import PermissionApprovalMiddleware
from ssw.subagents.text_to_sql import text_to_sql_subagent

SYSTEM_PROMPT = """
      你是一个企业级多功能智能体（Multi-Agent Assistant），负责理解用户需求、规划任务、选择合适技能并完成复杂工作。
      你的核心职责：
      1. 理解用户意图
      2. 分析任务类型
      3. 选择最合适的技能（Skill）
      4. 调用工具完成任务
    """

workspace = Path(SSW_WORKSPACE).resolve()
SKILLS_PATH = workspace / "skills/main"
SKILLS_PATH.mkdir(parents=True, exist_ok=True)
# redis短期记忆
# ttl_config = {
#     "default_ttl": 60 * 24 * 7,
#     "refresh_on_read": True,
# }
#
# try:
#     _checkpointer_cm = RedisSaver.from_conn_string(REDIS_URL, ttl=ttl_config)
#     checkpointer = _checkpointer_cm.__enter__()
#     checkpointer.setup()
# except Exception as exc:
#     print(f"Redis 检查点初始化失败，降级为进程内会话存储：{exc}", flush=True)
#     checkpointer = InMemorySaver()



subagents = [
    text_to_sql_subagent,
]

llm =build_llm()



def create_chat_agent(checkpoint: Any, tools: list[Any] | None = None):
    return  create_deep_agent(
    model=llm,
    tools=tools or [],
    middleware=[
        DynamicSkillsMiddleware(),
        PermissionApprovalMiddleware(),
        ToolCallLimitMiddleware(run_limit=10),
    ],
    system_prompt=SYSTEM_PROMPT,
    skills=[str(SKILLS_PATH)],
    subagents=subagents,
    interrupt_on={
    },
    checkpointer=checkpoint,
    backend=LocalShellBackend(root_dir=str(workspace), virtual_mode=True),
    name="ssw-agent",
)



