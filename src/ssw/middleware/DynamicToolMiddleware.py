from typing import NotRequired, TypedDict, Callable, Awaitable, Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ModelCallResult


class DynamicToolState(TypedDict, total=False):
    tool_metadata_all: NotRequired[list]


class DynamicToolMiddleware(AgentMiddleware):
    state_schema = DynamicToolState



    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        mcp_list = request.runtime.context["mcp_list"]
        overrides: dict[str, Any] = {}
        if mcp_list is not None:
            selected_mcp_servers = set(mcp_list)
            tools = []
            for tool in request.tools:
                metadata = getattr(tool, "metadata", None)
                mcp_server = metadata.get("mcpserver") if isinstance(metadata, dict) else None
                if mcp_server is None or mcp_server in selected_mcp_servers:
                    tools.append(tool)
            overrides["tools"] = tools
            request = request.override(**overrides)

        return await handler(request)