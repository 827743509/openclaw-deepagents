export type ThreadId = string;

export type ToolCallStatus = "running" | "done" | "error";

export type ToolCallProgress = {
  id: string;
  name: string;
  node?: string;
  status: ToolCallStatus;
};

export type StreamProgress = {
  node?: string;
  detail: string;
};

export type PermissionLevel = "low" | "high";

export type ToolApprovalRequest = {
  interruptId: string;
  toolCallId: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  description: string;
};

export type AsyncTaskStatus = {
  task_id: string;
  status: string;
  result?: string | null;
  error?: string | null;
};

export type StreamCallbacks = {
  onThreadId?: (threadId: ThreadId) => void;
  onAsyncTask?: (task: AsyncTaskStatus) => void;
  onApproval: (approval: ToolApprovalRequest) => boolean | Promise<boolean>;
  onToolCall: (toolCall: ToolCallProgress) => void;
  onProgress: (progress: StreamProgress) => void;
  onFinal: (content: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
};

export type ChatHistoryMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ChatHistory = {
  thread_id: ThreadId;
  messages: ChatHistoryMessage[];
};

export type ChatSummary = {
  thread_id: ThreadId;
  title: string;
  message_count: number;
  last_message: ChatHistoryMessage | null;
  updated_at: number;
};

export type ChatSummaryPage = {
  items: ChatSummary[];
  page: number;
  page_size: number;
  has_more: boolean;
};

export type SkillSummary = {
  id: string;
  name: string;
  description: string;
  skill_path: string;
  body?: string | null;
  metadata: Record<string, unknown>;
};

const apiUrl = import.meta.env.VITE_SSW_API_URL
  || (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function readContentPart(part: unknown): string {
  if (typeof part === "string") {
    return part;
  }

  const partRecord = asRecord(part);
  if (!partRecord) {
    return "";
  }

  const text = partRecord.text;
  return typeof text === "string" ? text : "";
}

function extractTextFromMessage(message: unknown): string {
  const messageRecord = asRecord(message);
  if (!messageRecord) {
    return "";
  }

  const content = messageRecord.content;
  if (typeof content === "string") {
    return content;
  }

  if (Array.isArray(content)) {
    return content.map(readContentPart).join("");
  }

  return "";
}

function messageType(message: unknown): string {
  const messageRecord = asRecord(message);
  if (!messageRecord) {
    return "";
  }

  const directType = messageRecord.type;
  if (typeof directType === "string") {
    return directType;
  }

  const id = messageRecord.id;
  return typeof id === "string" ? id : "";
}

function messageLooksLikeAi(message: unknown): boolean {
  const type = messageType(message).toLowerCase();
  return type.includes("ai") || type.includes("assistant");
}

function messageLooksLikeTool(message: unknown): boolean {
  const type = messageType(message).toLowerCase();
  return type.includes("tool");
}

function extractToolCalls(message: unknown): Array<{ id: string; name: string }> {
  const messageRecord = asRecord(message);
  if (!messageRecord) {
    return [];
  }

  const candidates = [
    messageRecord.tool_calls,
    messageRecord.toolCalls,
    messageRecord.additional_kwargs && asRecord(messageRecord.additional_kwargs)?.tool_calls,
  ];

  const toolCalls: Array<{ id: string; name: string }> = [];
  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue;
    }

    for (const item of candidate) {
      const itemRecord = asRecord(item);
      if (!itemRecord) {
        continue;
      }

      const rawFunction = asRecord(itemRecord.function);
      const name = itemRecord.name || rawFunction?.name;
      const id = itemRecord.id || name;
      if (typeof id === "string" && typeof name === "string") {
        toolCalls.push({ id, name });
      }
    }
  }

  return toolCalls;
}

function extractNode(metadata: unknown, fallback?: string): string | undefined {
  const metadataRecord = asRecord(metadata);
  const node = metadataRecord?.langgraph_node || metadataRecord?.node;
  return typeof node === "string" && node ? node : fallback;
}

function unpackMessageTuple(chunk: unknown): { message: unknown; metadata: unknown } | null {
  const chunkRecord = asRecord(chunk);
  const data = chunkRecord && "data" in chunkRecord ? chunkRecord.data : chunk;

  if (Array.isArray(data)) {
    return {
      message: data[0],
      metadata: data[1],
    };
  }

  return {
    message: data,
    metadata: undefined,
  };
}

function iterUpdateMessages(chunk: unknown): Array<{ node?: string; message: unknown }> {
  const chunkRecord = asRecord(chunk);
  const payload = chunkRecord && "data" in chunkRecord ? chunkRecord.data : chunk;
  const payloadRecord = asRecord(payload);
  if (!payloadRecord) {
    return [];
  }

  const messages: Array<{ node?: string; message: unknown }> = [];
  for (const [node, value] of Object.entries(payloadRecord)) {
    const valueRecord = asRecord(value);
    const nodeMessages = valueRecord?.messages;
    if (!Array.isArray(nodeMessages)) {
      continue;
    }

    for (const message of nodeMessages) {
      messages.push({ node, message });
    }
  }

  return messages;
}

function iterAsyncTasks(chunk: unknown): AsyncTaskStatus[] {
  const chunkRecord = asRecord(chunk);
  const payload = chunkRecord && "data" in chunkRecord ? chunkRecord.data : chunk;
  const payloadRecord = asRecord(payload);
  if (!payloadRecord) {
    return [];
  }

  const candidates = [payloadRecord];
  for (const value of Object.values(payloadRecord)) {
    const valueRecord = asRecord(value);
    if (valueRecord) {
      candidates.push(valueRecord);
    }
  }

  const tasks = new Map<string, AsyncTaskStatus>();
  for (const candidate of candidates) {
    const rawTasks = asRecord(candidate.async_tasks);
    if (!rawTasks) {
      continue;
    }

    for (const [taskId, rawTask] of Object.entries(rawTasks)) {
      const taskRecord = asRecord(rawTask);
      const resolvedTaskId = taskRecord?.task_id;
      const status = taskRecord?.status;
      if (typeof status !== "string") {
        continue;
      }
      const id = typeof resolvedTaskId === "string" ? resolvedTaskId : taskId;
      tasks.set(id, { task_id: id, status });
    }
  }
  return [...tasks.values()];
}

function iterToolApprovals(chunk: unknown): ToolApprovalRequest[] {
  const chunkRecord = asRecord(chunk);
  const payload = chunkRecord && "data" in chunkRecord ? chunkRecord.data : chunk;
  const payloadRecord = asRecord(payload);
  if (!payloadRecord) {
    return [];
  }

  const candidates = [payloadRecord, ...Object.values(payloadRecord)
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => Boolean(item))];
  const approvals = new Map<string, ToolApprovalRequest>();
  for (const candidate of candidates) {
    const interrupts = candidate.__interrupt__;
    if (!Array.isArray(interrupts)) {
      continue;
    }
    for (const rawInterrupt of interrupts) {
      const interruptRecord = asRecord(rawInterrupt);
      const value = asRecord(interruptRecord?.value);
      const interruptId = interruptRecord?.id;
      if (value?.type !== "tool_approval" || typeof interruptId !== "string") {
        continue;
      }
      const toolName = value.tool_name;
      const toolCallId = value.tool_call_id;
      if (typeof toolName !== "string" || typeof toolCallId !== "string") {
        continue;
      }
      approvals.set(interruptId, {
        interruptId,
        toolCallId,
        toolName,
        toolArgs: asRecord(value.tool_args) ?? {},
        description: typeof value.description === "string"
          ? value.description
          : `工具 ${toolName} 请求高权限操作`,
      });
    }
  }
  return [...approvals.values()];
}

export async function streamChatAnswer(
  threadId: ThreadId | null,
  question: string,
  signal: AbortSignal,
  callbacks: StreamCallbacks,
  skills: string[] = [],
  permissions: PermissionLevel = "low",
): Promise<void> {
  const seenToolCalls = new Set<string>();
  const finishedToolCalls = new Set<string>();
  const toolNamesById = new Map<string, string>();
  let finalText = "";

  function emitToolStart(tool: { id: string; name: string }, node?: string): void {
    if (seenToolCalls.has(tool.id)) {
      return;
    }

    seenToolCalls.add(tool.id);
    toolNamesById.set(tool.id, tool.name);
    callbacks.onToolCall({
      id: tool.id,
      name: tool.name,
      node,
      status: "running",
    });
    callbacks.onProgress({ node, detail: `正在调用 ${tool.name}` });
  }

  function emitToolEnd(message: unknown, node?: string): void {
    const record = asRecord(message);
    const id = record?.tool_call_id || record?.toolCallId || record?.name;
    if (typeof id !== "string" || finishedToolCalls.has(id)) {
      return;
    }

    finishedToolCalls.add(id);
    const name = toolNamesById.get(id) || (typeof record?.name === "string" ? record.name : "tool");
    callbacks.onToolCall({
      id,
      name,
      node,
      status: "done",
    });
    callbacks.onProgress({ node, detail: `${name} 已完成` });
  }

  function inspectMessage(message: unknown, node?: string, updateFinal = false): void {
    for (const toolCall of extractToolCalls(message)) {
      emitToolStart(toolCall, node);
    }

    if (messageLooksLikeTool(message)) {
      emitToolEnd(message, node);
    }

    if (updateFinal && messageLooksLikeAi(message)) {
      const text = extractTextFromMessage(message).trim();
      if (text) {
        finalText = text;
      }
    }
  }

  try {
    callbacks.onProgress({ detail: "模型正在处理" });
    let activeThreadId = threadId;
    let nextRequest: { url: string; body: Record<string, unknown> } | null = {
      url: `${apiUrl}/chat/stream`,
      body: { thread_id: threadId, question, skills, permissions },
    };

    while (nextRequest) {
      const currentRequest = nextRequest;
      nextRequest = null;
      const response = await fetch(currentRequest.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentRequest.body),
        signal,
      });
      if (!response.ok || !response.body) {
        const detail = await response.text();
        throw new Error(detail || `流式请求失败：${response.status}`);
      }

      const responseThreadId = response.headers.get("X-Thread-Id");
      if (responseThreadId) {
        const threadChanged = responseThreadId !== activeThreadId;
        activeThreadId = responseThreadId;
        if (threadChanged) {
          callbacks.onThreadId?.(responseThreadId);
        }
      }

      const roundApprovals = new Map<string, ToolApprovalRequest>();
      for await (const chunk of readEventStream(response.body)) {
        if (signal.aborted) {
          break;
        }

        const event = asRecord(chunk)?.event;
        const eventName = typeof event === "string" ? event : "";
        if (eventName.includes("error")) {
          const payload = asRecord(asRecord(chunk)?.data);
          throw new Error(typeof payload?.detail === "string" ? payload.detail : "流式请求失败");
        }
        if (eventName.includes("messages")) {
          const tuple = unpackMessageTuple(chunk);
          if (tuple) {
            inspectMessage(tuple.message, extractNode(tuple.metadata));
          }
          continue;
        }
        if (eventName.includes("updates")) {
          for (const approval of iterToolApprovals(chunk)) {
            roundApprovals.set(approval.interruptId, approval);
          }
          for (const task of iterAsyncTasks(chunk)) {
            callbacks.onAsyncTask?.(task);
          }
          for (const { node, message } of iterUpdateMessages(chunk)) {
            inspectMessage(message, node, true);
          }
        }
      }

      if (signal.aborted || !roundApprovals.size) {
        continue;
      }
      if (!activeThreadId) {
        throw new Error("缺少会话 ID，无法继续审批后的任务");
      }

      callbacks.onProgress({ detail: "等待高权限工具审批" });
      const decisions: Record<
        string,
        { type: "approve" } | { type: "reject"; message: string }
      > = {};
      for (const approval of roundApprovals.values()) {
        const approved = await callbacks.onApproval(approval);
        decisions[approval.interruptId] = approved
          ? { type: "approve" }
          : {
              type: "reject",
              message: `用户拒绝执行高权限工具 ${approval.toolName}`,
            };
      }
      callbacks.onProgress({ detail: "审批完成，正在继续执行" });
      nextRequest = {
        url: `${apiUrl}/chat/${encodeURIComponent(activeThreadId)}/resume`,
        body: { decisions, skills, permissions },
      };
    }

    callbacks.onFinal(finalText);
    callbacks.onDone();
  } catch (error) {
    if (signal.aborted) {
      callbacks.onDone();
      return;
    }

    callbacks.onError(error instanceof Error ? error.message : "流式请求失败");
  }
}

export function getLangGraphApiUrl(): string {
  return apiUrl;
}

export async function getChatHistory(threadId: ThreadId): Promise<ChatHistory> {
  const response = await fetch(`${apiUrl}/chat/${threadId}/history`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `加载会话历史失败：${response.status}`);
  }
  return (await response.json()) as ChatHistory;
}

export async function getAsyncTaskStatus(
  taskId: string,
  threadId: ThreadId,
): Promise<AsyncTaskStatus> {
  const query = new URLSearchParams({ thread_id: threadId });
  const response = await fetch(
    `${apiUrl}/chat/tasks/${encodeURIComponent(taskId)}?${query.toString()}`,
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `查询异步任务状态失败：${response.status}`);
  }
  return (await response.json()) as AsyncTaskStatus;
}

export async function listRecentChats(
  page = 1,
  pageSize = 10,
): Promise<ChatSummaryPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const response = await fetch(`${apiUrl}/chat?${query.toString()}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `加载最近会话失败：${response.status}`);
  }
  return (await response.json()) as ChatSummaryPage;
}

export async function listSkills(): Promise<SkillSummary[]> {
  const response = await fetch(`${apiUrl}/skills`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `加载技能失败：${response.status}`);
  }
  return (await response.json()) as SkillSummary[];
}

export async function importSkillZip(file: File): Promise<SkillSummary> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${apiUrl}/skills/import`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `导入 Skill 失败：${response.status}`);
  }
  return (await response.json()) as SkillSummary;
}

export async function deleteChat(threadId: ThreadId): Promise<void> {
  const response = await fetch(`${apiUrl}/chat/${threadId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `删除会话失败：${response.status}`);
  }
}

async function* readEventStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? "";
      for (const eventText of events) {
        const event = parseServerSentEvent(eventText);
        if (event) {
          yield event;
        }
      }
    }

    buffer += decoder.decode();
    const finalEvent = parseServerSentEvent(buffer);
    if (finalEvent) {
      yield finalEvent;
    }
  } finally {
    reader.releaseLock();
  }
}

function parseServerSentEvent(eventText: string): unknown | null {
  const lines = eventText.split(/\r?\n/);
  let event = "";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  const dataText = dataLines.join("\n");
  if (dataText === "[DONE]") {
    return null;
  }

  try {
    return {
      event,
      data: JSON.parse(dataText),
    };
  } catch {
    return {
      event,
      data: dataText,
    };
  }
}
