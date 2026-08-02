from __future__ import annotations

from pathlib import Path

from deepagents import CompiledSubAgent, create_deep_agent, AsyncSubAgent
from deepagents.backends.filesystem import FilesystemBackend

from ssw.config import SSW_AGENT_PROTOCOL_URL, SSW_WORKSPACE
from ssw.llm import build_llm
from ssw.subagents.text_to_sql.tool import validate_select_sql
workspace = Path(SSW_WORKSPACE).resolve()
SKILLS_PATH = workspace/"skills/text_to_sql"


SYSTEM_PROMPT = """
你是 text-to-SQL Agent，专门把用户的中文或英文自然语言问题转换为 SQL 查询语句。

工作边界：
- 只生成查询 SQL，不生成 INSERT、UPDATE、DELETE、DDL、权限变更或存储过程。
- 优先遵循用户问题中提供的当前数据源名称、类型和 SQL 方言。
- 如果当前数据源类型是 MySQL，生成 MySQL 查询语法。
- 如果当前数据源类型是 ClickHouse，生成 ClickHouse 查询语法。
- 必须优先阅读 Agent skills 目录中的表结构或数据源文档。
- 查询不到表结构时，回复未找到相关数据源或表结构。
- 缺少必要表结构时，先说明缺失信息，不要臆造表或字段。
- 生成 SQL 后必须调用 validate_select_sql 校验是否可以执行。
- 输出必须包含最终 SQL，并用简短中文说明用到的表、过滤条件、排序或聚合逻辑。
- 如果用户问题存在歧义，给出最合理假设；歧义会明显改变结果时，先要求补充条件。

SQL 规范：
- 字段和表名优先使用目标数据库方言支持的引用方式。
- 不使用 SELECT *，除非用户明确要求所有字段。
- 涉及时间范围时写清楚边界条件。
- 涉及分页时默认返回 10 条，除非用户指定数量。
- 对可能重复的业务实体，优先使用 COUNT(DISTINCT ...)。
"""

agent = create_deep_agent(
    model=build_llm(),
    tools=[validate_select_sql],
    system_prompt=SYSTEM_PROMPT,
    skills=[str(SKILLS_PATH)],
    backend=FilesystemBackend(root_dir=str(workspace), virtual_mode=True),
    name="text-to-sql-agent",
)

text_to_sql_subagent:AsyncSubAgent=AsyncSubAgent(
    name="text_to_sql",
    description="""
    专门负责将用户的数据查询需求转换为可执行的 SQL 查询语句。

    当用户需要从数据库中查询、统计、分析数据时调用此 Agent。
    输入通常是自然语言描述的数据需求，例如：
    - 根据条件筛选数据
    - 分组统计、聚合分析
    - 多表关联查询
    - 根据业务指标生成查询 SQL

    该 Agent 会理解业务含义，选择合适的数据表和字段，并生成 SELECT 类型 SQL。
    输出内容包括 SQL 查询语句以及必要的查询说明。

    不处理：
    - 数据写入、更新、删除操作（INSERT/UPDATE/DELETE）
    - 数据库结构设计
    - 非数据库相关的问题
    """,
    graph_id="text_to_sql",
    url=SSW_AGENT_PROTOCOL_URL
)
