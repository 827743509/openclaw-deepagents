<script setup lang="ts">
import { CheckCircle2, CircleX, Clock3, LoaderCircle } from "@lucide/vue";
import type { AsyncTaskStatus } from "../services/langgraph";

defineProps<{
  tasks: AsyncTaskStatus[];
}>();

function statusText(status: string): string {
  const labels: Record<string, string> = {
    pending: "等待执行",
    running: "执行中",
    success: "已完成",
    error: "执行失败",
    cancelled: "已取消",
    interrupted: "已中断",
    timeout: "已超时",
  };
  return labels[status] || status;
}

function isFailed(status: string): boolean {
  return ["error", "cancelled", "interrupted", "timeout"].includes(status);
}
</script>

<template>
  <div class="async-task-list">
    <section
      v-for="task in tasks"
      :key="task.task_id"
      class="async-task-card"
      :class="task.status"
    >
      <header>
        <LoaderCircle v-if="task.status === 'running'" :size="16" class="spin" />
        <CheckCircle2 v-else-if="task.status === 'success'" :size="16" />
        <CircleX v-else-if="isFailed(task.status)" :size="16" />
        <Clock3 v-else :size="16" />
        <strong>异步任务 · {{ statusText(task.status) }}</strong>
      </header>
      <small>{{ task.task_id }}</small>
      <p v-if="task.result" class="async-task-result">{{ task.result }}</p>
      <p v-if="task.error" class="async-task-error">{{ task.error }}</p>
    </section>
  </div>
</template>
