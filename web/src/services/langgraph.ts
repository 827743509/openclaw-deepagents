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

export type StreamCallbacks = {
  onThreadId?: (threadId: ThreadId) => void;
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

export type SkillSummary = {
  id: string;
  name: string;
  description: string;
  skill_path: string;
  body?: string | null;
  metadata: Record<string, unknown>;
};

const apiUrl = import.meta.env.VITE_SSW_API_URL || "http://127.0.0.1:8000";

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

export async function streamChatAnswer(
  threadId: ThreadId | null,
  question: string,
  signal: AbortSignal,
  callbacks: StreamCallbacks,
  context?: string,
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

    const response = await fetch(`${apiUrl}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ thread_id: threadId, question, context }),
      signal,
    });

    if (!response.ok || !response.body) {
      const detail = await response.text();
      throw new Error(detail || `流式请求失败：${response.status}`);
    }

    const responseThreadId = response.headers.get("X-Thread-Id");
    if (responseThreadId) {
      callbacks.onThreadId?.(responseThreadId);
    }

    for await (const chunk of readEventStream(response.body)) {
      if (signal.aborted) {
        break;
      }

      const event = asRecord(chunk)?.event;
      const eventName = typeof event === "string" ? event : "";

      if (eventName.includes("messages")) {
        const tuple = unpackMessageTuple(chunk);
        if (tuple) {
          inspectMessage(tuple.message, extractNode(tuple.metadata));
        }
        continue;
      }

      if (eventName.includes("updates")) {
        for (const { node, message } of iterUpdateMessages(chunk)) {
          inspectMessage(message, node, true);
        }
      }
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

export async function listRecentChats(limit = 10): Promise<ChatSummary[]> {
  const response = await fetch(`${apiUrl}/chat?limit=${limit}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `加载最近会话失败：${response.status}`);
  }
  return (await response.json()) as ChatSummary[];
}

export async function listSkills(): Promise<SkillSummary[]> {
  const response = await fetch(`${apiUrl}/skills`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `加载技能失败：${response.status}`);
  }
  return (await response.json()) as SkillSummary[];
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
