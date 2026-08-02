# 仓库指南

## 项目结构与模块组织

本仓库是一个 Python 3.11+ 的 LangGraph/Deep Agents 。源代码位于 `src/ssw/`：`agent.py` 定义 LangGraph agent，`config.py` 加载环境配置，`mcp_tools.py` 配置 MCP 工具连接，`langgraph.json` 将 `supervisor` 图暴露为 `src/ssw/agent.py:agent`。Agent 数据和技能位于 `data/`，包括 `data/memories/AGENTS.md` 和 `data/skills/`。运行时临时文件应放在 `workspace/`。

## 构建、测试与开发命令

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

创建本地环境，并以可编辑模式安装此包。使用 `uv` 时，优先运行 `uv sync` 依据 `uv.lock` 安装依赖。

```powershell
langgraph dev
```

使用 `langgraph.json` 和 `.env` 启动本地 LangGraph 开发服务器。

## 编码风格与命名约定

### 使用 4 个空格缩进、类型提示和显式导入。保持模块精简，并将包代码放在 `src/ssw` 内。函数、变量和模块名使用 `snake_case`；类和 Pydantic 模型使用 `PascalCase`。新增基于环境变量的设置时，请添加到 `src/ssw/config.py` 的 `Settings` 中，并使用清晰的别名，例如 `SSW_MODEL`。
### 生成的所有skills的md文件需要有YAML frontmatter 
### 后端封装流式事件，前端等待期间只显示“工具名 + 状态”，最终回答完成后一次性显示。
### 业务接口严格按照Api->Service->Repository 无数据层可以省略Repository  用 Depends + dependency.py 统一组装 Service和Repository对象默认单例使用@lru_cache 

## 子agent创建规范
### 创建一新的子agent时,需要在 `src/ssw/subagents` 下创建一个子agent目录。改目录包含skills(子agent特有的技能)和tool(子agent特有的工具) 并且需要在langgraph.json下面注册


