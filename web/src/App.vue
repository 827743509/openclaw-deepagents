<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleStop,
  LoaderCircle,
  RotateCcw,
  Send,
  Wrench,
} from "@lucide/vue";
import AppSidebar, { type SidebarView } from "./components/AppSidebar.vue";
import DataSourceManager from "./components/DataSourceManager.vue";
import {
  type ChatSummary,
  type SkillSummary,
  type ThreadId,
  type ToolCallProgress,
  deleteChat,
  getLangGraphApiUrl,
  getChatHistory,
  listRecentChats,
  listSkills,
  streamChatAnswer,
} from "./services/langgraph";

type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  thread?: ThreadId;
  status?: "streaming" | "done" | "error" | "stopped";
  toolCalls?: ToolCallProgress[];
};

const mainChatLabel = "SSW Agent";
const activeView = ref<SidebarView>("chat");
const currentThreadId = ref<ThreadId | null>(localStorage.getItem("ssw.currentThreadId"));
const inputText = ref("");
const isStreaming = ref(false);
const isLoadingThreads = ref(false);
const isLoadingSkills = ref(false);
const progressText = ref("待命中");
const threadError = ref("");
const skillError = ref("");
const skillSearchText = ref("");
const isSkillPickerOpen = ref(false);
const recentThreads = ref<ChatSummary[]>([]);
const skills = ref<SkillSummary[]>([]);
const selectedSkillIds = ref<string[]>(
  JSON.parse(localStorage.getItem("ssw.selectedSkillIds") || "[]") as string[],
);
const messages = ref<ChatMessage[]>([
  {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "你好，我是 SSW Agent。直接提问即可，我会在等待时展示工具调用过程，并在完成后输出最终回答。",
    status: "done",
  },
]);

const scrollRef = ref<HTMLElement | null>(null);
const abortController = ref<AbortController | null>(null);

const datasourceView = computed(() => (
  activeView.value === "datasource-create" ? "datasource-create" : "datasource-list"
));

const canSend = computed(() => {
  return Boolean(inputText.value.trim()) && !isStreaming.value;
});

const selectedSkills = computed(() => (
  selectedSkillIds.value
    .map((skillId) => skills.value.find((skill) => skill.id === skillId))
    .filter((skill): skill is SkillSummary => Boolean(skill))
));

const filteredSkills = computed(() => {
  const keyword = skillSearchText.value.trim().toLowerCase();
  if (!keyword) {
    return skills.value;
  }

  return skills.value.filter((skill) => (
    skill.name.toLowerCase().includes(keyword)
    || skill.description.toLowerCase().includes(keyword)
  ));
});

onMounted(() => {
  void refreshRecentThreads();
  void refreshSkills();
  if (currentThreadId.value) {
    void loadThread(currentThreadId.value);
  }
});

function chatLabel(_threadId?: ThreadId): string {
  return mainChatLabel;
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = scrollRef.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
}

function mapHistoryMessages(history: Awaited<ReturnType<typeof getChatHistory>>): ChatMessage[] {
  if (!history.messages.length) {
    return [];
  }

  return history.messages.map((message) => ({
    id: crypto.randomUUID(),
    role: message.role,
    content: message.content,
    thread: history.thread_id,
    status: "done",
  }));
}

async function refreshRecentThreads(): Promise<void> {
  isLoadingThreads.value = true;
  threadError.value = "";
  try {
    recentThreads.value = await listRecentChats(10);
  } catch (error) {
    threadError.value = error instanceof Error ? error.message : "加载最近会话失败";
  } finally {
    isLoadingThreads.value = false;
  }
}

async function refreshSkills(): Promise<void> {
  isLoadingSkills.value = true;
  skillError.value = "";
  try {
    skills.value = await listSkills();
    const availableIds = new Set(skills.value.map((skill) => skill.id));
    selectedSkillIds.value = selectedSkillIds.value.filter((skillId) => availableIds.has(skillId));
    persistSelectedSkills();
  } catch (error) {
    skillError.value = error instanceof Error ? error.message : "加载技能失败";
  } finally {
    isLoadingSkills.value = false;
  }
}

function persistSelectedSkills(): void {
  localStorage.setItem("ssw.selectedSkillIds", JSON.stringify(selectedSkillIds.value));
}

function toggleSkill(skillId: string): void {
  if (selectedSkillIds.value.includes(skillId)) {
    selectedSkillIds.value = selectedSkillIds.value.filter((item) => item !== skillId);
  } else {
    selectedSkillIds.value = [...selectedSkillIds.value, skillId];
  }
  persistSelectedSkills();
}

function removeSkill(skillId: string): void {
  selectedSkillIds.value = selectedSkillIds.value.filter((item) => item !== skillId);
  persistSelectedSkills();
}

function buildSkillContext(): string | undefined {
  if (!selectedSkills.value.length) {
    return undefined;
  }

  return [
    "用户在前端选择了以下技能，请优先结合这些技能的用途回答：",
    ...selectedSkills.value.map((skill) => `- ${skill.name}: ${skill.description}`),
  ].join("\n");
}

async function loadThread(threadId: ThreadId): Promise<void> {
  if (isStreaming.value) {
    return;
  }

  threadError.value = "";
  try {
    const history = await getChatHistory(threadId);
    currentThreadId.value = history.thread_id;
    localStorage.setItem("ssw.currentThreadId", history.thread_id);
    messages.value = mapHistoryMessages(history);
    if (!messages.value.length) {
      messages.value = [];
    }
    progressText.value = "会话已加载";
    await scrollToBottom();
  } catch (error) {
    threadError.value = error instanceof Error ? error.message : "加载会话失败";
  }
}

async function resetChat(): Promise<void> {
  if (isStreaming.value) {
    stopStreaming();
  }

  if (currentThreadId.value) {
    try {
      await deleteChat(currentThreadId.value);
    } catch {
      progressText.value = "删除会话失败";
      return;
    }
    localStorage.removeItem("ssw.currentThreadId");
    currentThreadId.value = null;
  }

  messages.value = [];
  await refreshRecentThreads();
  progressText.value = "已清空";
}

async function startNewChat(): Promise<void> {
  if (isStreaming.value) {
    stopStreaming();
  }

  localStorage.removeItem("ssw.currentThreadId");
  currentThreadId.value = null;
  activeView.value = "chat";
  messages.value = [];
  progressText.value = "新聊天已就绪";
  await refreshRecentThreads();
}

function navigateView(view: SidebarView): void {
  activeView.value = view;
}

function upsertToolCall(message: ChatMessage, toolCall: ToolCallProgress): void {
  const toolCalls = message.toolCalls ?? [];
  const existing = toolCalls.find((item) => item.id === toolCall.id);

  if (existing) {
    existing.name = toolCall.name;
    existing.node = toolCall.node || existing.node;
    existing.status = toolCall.status;
  } else {
    toolCalls.push(toolCall);
  }

  message.toolCalls = toolCalls;
}

function stopStreaming(): void {
  abortController.value?.abort();
  const lastAssistant = [...messages.value].reverse().find((message) => message.role === "assistant");
  if (lastAssistant?.status === "streaming") {
    lastAssistant.status = "stopped";
    if (!lastAssistant.content.trim()) {
      lastAssistant.content = "已停止生成。";
    }
  }
  isStreaming.value = false;
  progressText.value = "已停止";
}

async function sendMessage(): Promise<void> {
  const question = inputText.value.trim();
  if (!question || isStreaming.value) {
    return;
  }

  const assistantMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "assistant",
    thread: currentThreadId.value ?? undefined,
    content: "",
    status: "streaming",
    toolCalls: [],
  };

  messages.value.push({
    id: crypto.randomUUID(),
    role: "user",
    content: question,
    status: "done",
  });
  messages.value.push(assistantMessage);

  inputText.value = "";
  isStreaming.value = true;
  progressText.value = `${chatLabel(currentThreadId.value ?? undefined)} 正在处理`;
  abortController.value = new AbortController();
  await scrollToBottom();

  await streamChatAnswer(currentThreadId.value, question, abortController.value.signal, {
    onThreadId(createdThreadId) {
      currentThreadId.value = createdThreadId;
      assistantMessage.thread = createdThreadId;
      localStorage.setItem("ssw.currentThreadId", createdThreadId);
      void refreshRecentThreads();
    },
    onToolCall(toolCall) {
      upsertToolCall(assistantMessage, toolCall);
      void scrollToBottom();
    },
    onProgress(progress) {
      progressText.value = progress.node
        ? `${progress.node} · ${progress.detail}`
        : progress.detail;
    },
    onFinal(content) {
      assistantMessage.content = content || "本次运行没有返回最终文本。";
      void scrollToBottom();
    },
    onDone() {
      if (assistantMessage.status === "streaming") {
        assistantMessage.status = "done";
      }
      isStreaming.value = false;
      progressText.value = "回复完成";
      abortController.value = null;
      void refreshRecentThreads();
      void scrollToBottom();
    },
    onError(message) {
      assistantMessage.status = "error";
      assistantMessage.content = assistantMessage.content
        ? `${assistantMessage.content}\n\n请求失败：${message}`
        : `请求失败：${message}`;
      isStreaming.value = false;
      progressText.value = "请求失败";
      abortController.value = null;
      void refreshRecentThreads();
      void scrollToBottom();
    },
  }, buildSkillContext());
}

function handleKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    void sendMessage();
  }
}
</script>

<template>
  <main class="app-shell">
    <AppSidebar
      :active-view="activeView"
      :current-thread-id="currentThreadId"
      :is-loading-threads="isLoadingThreads"
      :is-streaming="isStreaming"
      :progress-text="progressText"
      :api-url="getLangGraphApiUrl()"
      :recent-threads="recentThreads"
      :thread-error="threadError"
      @new-chat="startNewChat"
      @navigate="navigateView"
      @load-thread="loadThread"
      @refresh-history="refreshRecentThreads"
    />

    <section v-if="activeView === 'chat'" class="chat-workspace" aria-label="问答聊天区">
      <header class="chat-header">
        <div>
          <p class="eyebrow">问答终端</p>
          <h2>{{ mainChatLabel }}</h2>
        </div>
        <button class="icon-button" type="button" title="删除会话" @click="resetChat">
          <RotateCcw :size="20" />
        </button>
      </header>

      <div ref="scrollRef" class="message-list">
        <article
          v-for="message in messages"
          :key="message.id"
          class="message-row"
          :class="message.role"
        >
          <div class="avatar">
            <Bot v-if="message.role === 'assistant'" :size="18" />
            <span v-else>你</span>
          </div>
          <div class="bubble" :class="message.status">
            <div v-if="message.role === 'assistant'" class="bubble-meta">
              {{ chatLabel(message.thread) }}
            </div>

            <div
              v-if="message.role === 'assistant' && message.status === 'streaming'"
              class="tool-progress"
            >
              <div v-if="!message.toolCalls?.length" class="tool-row running">
                <LoaderCircle :size="16" />
                <span>模型正在处理</span>
              </div>
              <div
                v-for="tool in message.toolCalls"
                :key="tool.id"
                class="tool-row"
                :class="tool.status"
              >
                <LoaderCircle v-if="tool.status === 'running'" :size="16" />
                <CheckCircle2 v-else-if="tool.status === 'done'" :size="16" />
                <Wrench v-else :size="16" />
                <span>{{ tool.name }}</span>
                <small v-if="tool.node">{{ tool.node }}</small>
              </div>
            </div>

            <p v-if="message.content">{{ message.content }}</p>
          </div>
        </article>
      </div>

      <form class="composer" @submit.prevent="sendMessage">
        <textarea
          v-model="inputText"
          rows="3"
          placeholder="输入问题，Ctrl + Enter 发送"
          :disabled="isStreaming"
          @keydown="handleKeydown"
        ></textarea>
        <div class="composer-actions">
          <div class="skill-toolbar">
            <div class="skill-picker">
              <button
                class="skill-trigger"
                type="button"
                :class="{ active: isSkillPickerOpen || selectedSkills.length }"
                @click="isSkillPickerOpen = !isSkillPickerOpen"
              >
                <Wrench :size="16" />
                技能
                <ChevronDown :size="15" />
              </button>
              <div v-if="isSkillPickerOpen" class="skill-popover">
                <label class="skill-search">
                  <span>搜索技能</span>
                  <input v-model.trim="skillSearchText" placeholder="搜索技能" />
                </label>
                <div class="skill-list">
                  <button
                    v-for="skill in filteredSkills"
                    :key="skill.id"
                    class="skill-option"
                    :class="{ selected: selectedSkillIds.includes(skill.id) }"
                    type="button"
                    @click="toggleSkill(skill.id)"
                  >
                    <span class="skill-avatar">{{ skill.name.slice(0, 1).toUpperCase() }}</span>
                    <span>
                      <strong>{{ skill.name }}</strong>
                      <small>{{ skill.description }}</small>
                    </span>
                  </button>
                  <p v-if="isLoadingSkills" class="skill-empty">加载技能中</p>
                  <p v-else-if="!filteredSkills.length" class="skill-empty">没有匹配的技能</p>
                  <p v-if="skillError" class="inline-error">{{ skillError }}</p>
                </div>
              </div>
            </div>
            <div v-if="selectedSkills.length" class="selected-skills">
              <button
                v-for="skill in selectedSkills"
                :key="skill.id"
                class="skill-chip"
                type="button"
                @click="removeSkill(skill.id)"
              >
                {{ skill.name }}
              </button>
            </div>
          </div>
          <div class="send-actions">
            <button
              v-if="isStreaming"
              class="send-button stop"
              type="button"
              @click="stopStreaming"
            >
              <CircleStop :size="20" />
              停止
            </button>
            <button v-else class="send-button" type="submit" :disabled="!canSend">
              <Send :size="20" />
              发送
            </button>
          </div>
        </div>
      </form>
    </section>
    <DataSourceManager
      v-else
      :view="datasourceView"
      class="manager-workspace"
      @navigate="navigateView"
    />
  </main>
</template>
