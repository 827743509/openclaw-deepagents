# SSW Agent

这是一个基于 LangGraph/Deep Agents 的个人 AI assistant 项目。

## 安装使用

要求 Python 3.11～3.13。通过 pip 安装：

```powershell
pip install ssw-agent
```

安装后直接启动：

```powershell
ssw-agent
```

如果 Python 的 Scripts 目录不在 `PATH` 中，也可以使用模块方式启动：

```powershell
python -m ssw.start_web
```

默认使用当前用户主目录下的 `.ssw` 作为 workspace。Windows 默认路径为
`C:\Users\<用户名>\.ssw`，其中会保存：

- `.env`：模型及服务配置，需要由使用者自行创建，不会包含在安装包中；
- `skills/`：主 Agent 和子 Agent 的技能文件；
- `mcp.json`：MCP 服务配置；
- `.checkpoint/`：本地会话检查点。

首次启动会从安装包初始化默认 `mcp.json` 和主 Agent skills。初始化只复制
缺失文件，不会覆盖用户已经修改的配置或技能。Text-to-SQL 数据源 skills
可能包含数据库连接凭据，因此不会作为默认资源发布。

首次启动前可以手动创建 `.ssw/.env` 并填写模型配置：

```dotenv
SSW_API_KEY=你的模型密钥
SSW_BASE_URL=https://api.deepseek.com
SSW_MODEL=deepseek-chat
```

也可以通过系统环境变量 `SSW_WORKSPACE` 指定其他目录：

```powershell
$env:SSW_WORKSPACE = "D:\ssw-workspace"
ssw-agent
```

启动后访问 `http://127.0.0.1:8000`。程序会使用安装包内的 LangGraph 配置启动异步子 Agent 服务，不依赖源码仓库中的 `langgraph.json`。

## 本地开发

优先使用 `uv` 同步依赖：

```powershell
uv sync
```

在仓库根目录启动 Web 服务：

```powershell
python -m ssw.start_web
```

`ssw.start_web` 会先启动 `langgraph dev` 作为异步子 Agent 服务，默认监听 `http://127.0.0.1:2024`；随后启动 FastAPI，默认监听 `http://127.0.0.1:8000`。前端和业务接口统一访问 FastAPI，Chat 接口在当前 FastAPI 进程内直接调用 `agent.astream`。

## Chat API

- `POST /chat/stream`：流式对话。请求体可不传 `thread_id`，后端会生成会话线程 id，并通过响应头 `X-Thread-Id` 返回。
- `GET /chat?limit=10`：查询最近会话列表，默认返回最近 10 次。
- `GET /chat/{thread_id}/history`：查看会话历史。
- `DELETE /chat/{thread_id}`：删除会话。


