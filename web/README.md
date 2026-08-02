# SSW Agent Web

Vue3 二次元风格问答页面，通过 FastAPI 访问当前仓库的 LangGraph 智能体。

## 开发运行

```powershell
cd web
npm install
npm run dev
```

默认访问地址为 `http://127.0.0.1:9000`。

## 后端依赖

前端默认连接 `http://127.0.0.1:8000` 的 FastAPI。请在仓库根目录启动：

```powershell
python -m ssw.start_web
```

如需修改 API 地址，复制 `.env.example` 为 `.env` 并设置：

```powershell
VITE_SSW_API_URL=http://127.0.0.1:8000
```

## 支持的对话

- `chat`

该 ID 与仓库根目录的 `langgraph.json` 保持一致。页面使用后端返回的 `thread_id` 维护会话，首次发送时不需要前端生成会话线程 id。
