# SSW Agent

## Docker Compose 部署

先根据 `.env.example` 创建 `.env`，并填写模型密钥等必要配置，然后构建并启动全部服务：

```powershell
docker compose up -d --build
```

默认访问地址：

- 前端：`http://localhost:9001`
- 后端 API：`http://localhost:8000`
- Agent Protocol：`http://localhost:2024`
- Redis：`localhost:6379`
- MongoDB：`localhost:27017`

首次启动时，`mongo-init` 会自动初始化 MongoDB 副本集。前端通过 Nginx 的 `/api` 路径代理后端，并已关闭 SSE 响应缓冲。

这是一个基于 LangGraph/Deep Agents 的个人 AI assistant 项目。

## 安装使用
### pip
pip install  ssw_agent

### docker
 
## 本地开发

优先使用 `uv` 同步依赖：

```powershell
uv sync
```

启动 Web 后端：

```powershell
python -m ssw.start_web
```

`ssw.start_web` 会先启动 `langgraph dev` 作为异步子 Agent 服务，默认监听 `http://127.0.0.1:2024`；随后启动 FastAPI，默认监听 `http://127.0.0.1:8000`。前端和业务接口统一访问 FastAPI，Chat 接口在当前 FastAPI 进程内直接调用 `agent.astream`。

## Chat API

- `POST /chat/stream`：流式对话。请求体可不传 `thread_id`，后端会生成会话线程 id，并通过响应头 `X-Thread-Id` 返回。
- `GET /chat?limit=10`：查询最近会话列表，默认返回最近 10 次。
- `GET /chat/{thread_id}/history`：查看会话历史。
- `DELETE /chat/{thread_id}`：删除会话。

`thread_id` 是后端生成的会话线程 id，不是 LangGraph 的 assistant id。LangGraph assistant 固定使用 `chat`。
