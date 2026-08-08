import { onBeforeUnmount } from "vue";
import {
  getAsyncTaskStatus,
  type AsyncTaskStatus,
  type ThreadId,
} from "../services/langgraph";

type TaskUpdateHandler = (task: AsyncTaskStatus) => void;
type TaskPollingContext = {
  threadId: ThreadId;
  onUpdate: TaskUpdateHandler;
};

type PollingOptions = {
  intervalMs?: number;
  onError?: (error: unknown) => void;
  onTerminal?: (task: AsyncTaskStatus, threadId: ThreadId) => void;
};

const terminalStatuses = new Set([
  "success",
  "error",
  "cancelled",
  "interrupted",
  "timeout",
]);

export function useAsyncTaskPolling(options: PollingOptions = {}) {
  const intervalMs = options.intervalMs ?? 30_000;
  const pollingContexts = new Map<string, TaskPollingContext>();
  const pollsInFlight = new Set<string>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();

  function isTerminal(status: string): boolean {
    return terminalStatuses.has(status);
  }

  function stop(taskId: string): void {
    pollingContexts.delete(taskId);
    const timer = timers.get(taskId);
    if (timer) {
      clearTimeout(timer);
      timers.delete(taskId);
    }
  }

  function stopAll(): void {
    for (const taskId of [...pollingContexts.keys()]) {
      stop(taskId);
    }
  }

  function schedule(taskId: string): void {
    if (!pollingContexts.has(taskId)) {
      return;
    }
    const timer = setTimeout(() => {
      timers.delete(taskId);
      void poll(taskId);
    }, intervalMs);
    timers.set(taskId, timer);
  }

  async function poll(taskId: string): Promise<void> {
    const context = pollingContexts.get(taskId);
    if (!context || pollsInFlight.has(taskId)) {
      return;
    }

    pollsInFlight.add(taskId);
    try {
      const task = await getAsyncTaskStatus(taskId, context.threadId);
      const currentContext = pollingContexts.get(taskId);
      if (!currentContext) {
        return;
      }
      currentContext.onUpdate(task);
      if (isTerminal(task.status)) {
        stop(taskId);
        options.onTerminal?.(task, currentContext.threadId);
        return;
      }
    } catch (error) {
      if (pollingContexts.has(taskId)) {
        options.onError?.(error);
      }
    } finally {
      pollsInFlight.delete(taskId);
    }

    schedule(taskId);
  }

  function start(
    task: AsyncTaskStatus,
    threadId: ThreadId,
    onUpdate: TaskUpdateHandler,
  ): void {
    onUpdate(task);
    if (isTerminal(task.status)) {
      stop(task.task_id);
      options.onTerminal?.(task, threadId);
      return;
    }
    if (pollingContexts.has(task.task_id)) {
      pollingContexts.set(task.task_id, { threadId, onUpdate });
      return;
    }
    pollingContexts.set(task.task_id, { threadId, onUpdate });
    void poll(task.task_id);
  }

  onBeforeUnmount(stopAll);

  return {
    start,
    stopAll,
  };
}
