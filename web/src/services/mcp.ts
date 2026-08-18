export type McpConfig = {
  mcpServers: Record<string, Record<string, unknown>>;
};

export type McpApplyResult = {
  config: McpConfig;
  loaded_servers: string[];
  tool_count: number;
};

const apiUrl = import.meta.env.VITE_SSW_API_URL
  || (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

async function readError(response: Response, fallback: string): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return new Error(payload.detail);
    }
    if (Array.isArray(payload.detail)) {
      const messages = payload.detail
        .map((item) => {
          if (!item || typeof item !== "object") {
            return "";
          }
          const detail = item as { loc?: unknown; msg?: unknown };
          const location = Array.isArray(detail.loc)
            ? detail.loc.filter((part) => part !== "body").join(".")
            : "";
          const message = typeof detail.msg === "string" ? detail.msg : "配置格式错误";
          return location ? `${location}：${message}` : message;
        })
        .filter(Boolean);
      if (messages.length) {
        return new Error(messages.join("；"));
      }
    }
  } catch {
    // 非 JSON 错误响应使用统一提示。
  }
  return new Error(`${fallback}：${response.status}`);
}

export async function getMcpConfig(): Promise<McpConfig> {
  const response = await fetch(`${apiUrl}/mcp/config`);
  if (!response.ok) {
    throw await readError(response, "加载 MCP 配置失败");
  }
  return (await response.json()) as McpConfig;
}

export async function getEnabledMcpServerNames(): Promise<string[]> {
  const config = await getMcpConfig();
  return Object.entries(config.mcpServers)
    .filter(([, server]) => server.disabled !== true && server.enabled !== false)
    .map(([name]) => name);
}

export async function updateMcpConfig(config: McpConfig): Promise<McpApplyResult> {
  const response = await fetch(`${apiUrl}/mcp/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw await readError(response, "保存 MCP 配置失败");
  }
  return (await response.json()) as McpApplyResult;
}
