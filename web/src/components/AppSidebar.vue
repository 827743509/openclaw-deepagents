<script setup lang="ts">
import {
  Database,
  History,
  LoaderCircle,
  MessageSquarePlus,
  RotateCcw,
  Sparkles,
  TableProperties,
} from "@lucide/vue";
import type { ChatSummary, ThreadId } from "../services/langgraph";

export type SidebarView = "chat" | "datasource-list" | "datasource-create";

defineProps<{
  activeView: SidebarView;
  currentThreadId: ThreadId | null;
  isLoadingThreads: boolean;
  hasMoreThreads: boolean;
  isStreaming: boolean;
  progressText: string;
  apiUrl: string;
  recentThreads: ChatSummary[];
  threadError: string;
}>();

const emit = defineEmits<{
  newChat: [];
  navigate: [view: SidebarView];
  loadThread: [threadId: ThreadId];
  refreshHistory: [];
  loadMoreHistory: [];
}>();

function openNewChat(): void {
  emit("newChat");
}

function threadTitle(thread: ChatSummary): string {
  return thread.title.trim() || "新会话";
}

function formatThreadTime(value: number): string {
  return new Date(value * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function handleHistoryScroll(event: Event): void {
  const element = event.currentTarget as HTMLElement;
  const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
  if (distanceToBottom <= 32) {
    emit("loadMoreHistory");
  }
}
</script>

<template>
  <aside class="sidebar app-menu" aria-label="主菜单">
    <div class="menu-brand">
      <div class="brand-mark menu-brand-mark">
        <Sparkles :size="22" />
      </div>
      <div>
        <p class="eyebrow">SSW Agent</p>
        <h1>盐汽水问答终端</h1>
      </div>
    </div>

    <nav class="menu-nav" aria-label="功能菜单">
      <button
        class="menu-item"
        :class="{ active: activeView === 'chat' }"
        type="button"
        :disabled="isStreaming"
        @click="openNewChat"
      >
        <MessageSquarePlus :size="19" />
        <span>新聊天</span>
      </button>

      <button
        class="menu-item"
        :class="{ active: activeView === 'datasource-list' || activeView === 'datasource-create' }"
        type="button"
        @click="emit('navigate', 'datasource-list')"
      >
        <Database :size="19" />
        <span>text_to_sql 数据源管理</span>
      </button>
    </nav>

    <section class="menu-group" aria-label="text_to_sql">
      <p class="menu-group-title">text_to_sql</p>
      <div class="menu-status">
        <TableProperties :size="16" />
        <span>数据源 Skill 管理</span>
      </div>
    </section>

    <section class="history-panel menu-history" aria-label="历史会话">
      <div class="panel-heading">
        <p class="panel-title">历史会话</p>
        <button
          class="mini-icon-button"
          type="button"
          title="刷新历史"
          :disabled="isLoadingThreads"
          @click="emit('refreshHistory')"
        >
          <RotateCcw :size="16" />
        </button>
      </div>
      <div class="history-list" @scroll.passive="handleHistoryScroll">
        <button
          v-for="thread in recentThreads"
          :key="thread.thread_id"
          class="history-item"
          :class="{ active: currentThreadId === thread.thread_id }"
          type="button"
          :disabled="isStreaming"
          @click="emit('loadThread', thread.thread_id)"
        >
          <History :size="16" />
          <span>
            <strong>{{ threadTitle(thread) }}</strong>
            <small>{{ formatThreadTime(thread.updated_at) }}</small>
          </span>
        </button>
        <p v-if="!isLoadingThreads && !recentThreads.length" class="history-empty">暂无历史会话</p>
        <p v-if="isLoadingThreads && recentThreads.length" class="history-loading">
          <LoaderCircle :size="15" />
          加载更多会话
        </p>
        <p
          v-else-if="!hasMoreThreads && recentThreads.length"
          class="history-page-end"
        >
          已加载全部会话
        </p>
        <p v-if="threadError" class="inline-error">{{ threadError }}</p>
      </div>
    </section>

    <div class="status-card menu-footer">
      <span class="pulse-dot" :class="{ streaming: isStreaming }"></span>
      <div>
        <strong>{{ progressText }}</strong>
        <small>{{ apiUrl }}</small>
      </div>
    </div>
  </aside>
</template>
