from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt


class PermissionApprovalMiddleware(AgentMiddleware):
    """在低权限模式下审批 metadata.permissions=high 的工具。"""

    HIGH_PERMISSION_TOOLS = [
        "write_file",
        "edit_file",
        "execute",
    ]

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        request_permissions = request.runtime.context.get("permissions", "low")
        #允许的权限等级为高直接放行
        if request_permissions == "high":
            return await handler(request)

        tool_metadata = request.tool.metadata if request.tool else None
        tool_name = request.tool_call["name"]
        # HIGH_PERMISSION_TOOLS中的工具所需权限为high
        if tool_name in self.HIGH_PERMISSION_TOOLS:
            tool_permission = "high"
        else:
            tool_permission = (
                tool_metadata.get("permissions")
                if isinstance(tool_metadata, dict)
                else None
            )

        if tool_permission != "high":
            return await handler(request)

        tool_call = request.tool_call
        decision = interrupt(
            {
                "type": "tool_approval",
                "tool_call_id": tool_call["id"],
                "tool_name": tool_call["name"],
                "tool_args": tool_call.get("args", {}),
                "description": f"工具 {tool_call['name']} 请求高权限操作，是否允许执行？",
            }
        )
        if isinstance(decision, dict) and decision.get("type") == "approve":
            return await handler(request)

        return ToolMessage(
            content=(
                decision.get("message")
                if isinstance(decision, dict) and isinstance(decision.get("message"), str)
                else f"用户拒绝执行高权限工具 {tool_call['name']}"
            ),
            name=tool_call["name"],
            tool_call_id=tool_call["id"],
            status="error",
        )
