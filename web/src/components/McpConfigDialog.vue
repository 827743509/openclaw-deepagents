<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  ArrowLeft,
  CircleCheck,
  CircleOff,
  LoaderCircle,
  Save,
  Server,
  Settings,
  X,
} from "@lucide/vue";
import {
  type McpConfig,
  getMcpConfig,
  updateMcpConfig,
} from "../services/mcp";

const emit = defineEmits<{
  close: [];
}>();

const configText = ref("");
const config = ref<McpConfig>({ mcpServers: {} });
const currentView = ref<"list" | "config">("list");
const isLoading = ref(true);
const isSaving = ref(false);
const togglingServerName = ref<string | null>(null);
const errorText = ref("");
const successText = ref("");
const canSave = computed(() => (
  !isLoading.value && !isSaving.value && Boolean(configText.value.trim())
));
const serverEntries = computed(() => Object.entries(config.value.mcpServers));

onMounted(() => {
  void loadConfig();
});

async function loadConfig(): Promise<void> {
  isLoading.value = true;
  errorText.value = "";
  try {
    const config = await getMcpConfig();
    setConfig(config);
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "加载 MCP 配置失败";
  } finally {
    isLoading.value = false;
  }
}

function setConfig(value: McpConfig): void {
  config.value = value;
  configText.value = JSON.stringify(value, null, 2);
}

function openConfigEditor(): void {
  configText.value = JSON.stringify(config.value, null, 2);
  errorText.value = "";
  successText.value = "";
  currentView.value = "config";
}

function backToList(): void {
  errorText.value = "";
  successText.value = "";
  currentView.value = "list";
}

function serverTransport(server: Record<string, unknown>): string {
  if (typeof server.type === "string") {
    return server.type;
  }
  if (typeof server.transport === "string") {
    return server.transport;
  }
  if (typeof server.command === "string") {
    return "stdio";
  }
  if (typeof server.url === "string") {
    return "streamable_http";
  }
  return "未识别";
}

function isServerDisabled(server: Record<string, unknown>): boolean {
  return server.disabled === true || server.enabled === false;
}

async function toggleServer(
  name: string,
  server: Record<string, unknown>,
): Promise<void> {
  if (togglingServerName.value) {
    return;
  }

  errorText.value = "";
  successText.value = "";
  togglingServerName.value = name;
  const willDisable = !isServerDisabled(server);
  try {
    const nextConfig = JSON.parse(JSON.stringify(config.value)) as McpConfig;
    const nextServer = nextConfig.mcpServers[name];
    delete nextServer.enabled;
    nextServer.disabled = willDisable;
    const result = await updateMcpConfig(nextConfig);
    setConfig(result.config);
    successText.value = `${name} 已${willDisable ? "停用" : "启用"}`;
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "更新 MCP 应用状态失败";
  } finally {
    togglingServerName.value = null;
  }
}

function parseConfig(): McpConfig {
  let parsed: unknown;
  try {
    parsed = JSON.parse(configText.value);
  } catch (error) {
    const message = error instanceof Error ? error.message : "未知格式错误";
    throw new Error(`JSON 格式错误：${message}`);
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("MCP 配置必须是 JSON 对象");
  }
  if (!("mcpServers" in parsed)) {
    throw new Error("MCP 配置必须包含 mcpServers 字段");
  }
  return parsed as McpConfig;
}

async function saveConfig(): Promise<void> {
  errorText.value = "";
  successText.value = "";
  isSaving.value = true;
  try {
    const result = await updateMcpConfig(parseConfig());
    setConfig(result.config);
    successText.value = `配置已应用，共加载 ${result.tool_count} 个 MCP 工具`;
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存 MCP 配置失败";
  } finally {
    isSaving.value = false;
  }
}
</script>

<template>
  <div class="mcp-dialog-backdrop" @click.self="emit('close')">
    <section class="mcp-dialog" role="dialog" aria-modal="true" aria-label="MCP 配置">
      <header class="mcp-dialog-header">
        <div>
          <p class="eyebrow">{{ currentView === "list" ? "MCP Apps" : "mcp.json" }}</p>
          <h2>{{ currentView === "list" ? "MCP 应用" : "MCP 配置" }}</h2>
        </div>
        <div class="mcp-header-actions">
          <button
            v-if="currentView === 'config'"
            class="mini-icon-button"
            type="button"
            aria-label="返回应用列表"
            @click="backToList"
          >
            <ArrowLeft :size="18" />
          </button>
          <button class="mini-icon-button" type="button" aria-label="关闭" @click="emit('close')">
            <X :size="18" />
          </button>
        </div>
      </header>

      <div
        class="mcp-dialog-body"
        :class="{ 'mcp-config-editor-body': currentView === 'config' }"
      >
        <div v-if="isLoading" class="mcp-loading">
          <LoaderCircle :size="18" />
          <span>正在加载配置</span>
        </div>

        <template v-else-if="currentView === 'list'">
          <div v-if="serverEntries.length" class="mcp-app-list">
            <article v-for="[name, server] in serverEntries" :key="name" class="mcp-app-card">
              <span class="mcp-app-icon"><Server :size="22" /></span>
              <span class="mcp-app-info">
                <strong>{{ name }}</strong>
                <small>{{ serverTransport(server) }}</small>
              </span>
              <button
                class="mcp-app-status"
                :class="{ disabled: isServerDisabled(server) }"
                type="button"
                :disabled="Boolean(togglingServerName)"
                @click="toggleServer(name, server)"
              >
                <LoaderCircle v-if="togglingServerName === name" :size="15" />
                <CircleOff v-else-if="isServerDisabled(server)" :size="15" />
                <CircleCheck v-else :size="15" />
                {{ togglingServerName === name
                  ? "处理中"
                  : (isServerDisabled(server) ? "已停用" : "已启用") }}
              </button>
            </article>
          </div>
          <div v-else class="mcp-app-empty">
            <Server :size="34" />
            <strong>还没有 MCP 应用</strong>
            <span>点击“配置应用”编辑 mcp.json</span>
          </div>
          <p v-if="errorText" class="inline-error">{{ errorText }}</p>
          <p v-if="successText" class="mcp-success">{{ successText }}</p>
        </template>

        <template v-else>
          <textarea
            v-model="configText"
            class="mcp-json-editor"
            spellcheck="false"
            aria-label="mcp.json 内容"
          ></textarea>
          <p v-if="errorText" class="inline-error">{{ errorText }}</p>
          <p v-if="successText" class="mcp-success">{{ successText }}</p>
        </template>
      </div>

      <footer v-if="!isLoading" class="mcp-dialog-footer">
        <span v-if="currentView === 'config'">保存后立即重新加载 MCP 工具</span>
        <span v-else>共 {{ serverEntries.length }} 个 MCP 应用</span>
        <button
          v-if="currentView === 'list'"
          class="primary-button"
          type="button"
          @click="openConfigEditor"
        >
          <Settings :size="17" />
          配置应用
        </button>
        <button
          v-else
          class="primary-button"
          type="button"
          :disabled="!canSave"
          @click="saveConfig"
        >
          <LoaderCircle v-if="isSaving" :size="17" />
          <Save v-else :size="17" />
          {{ isSaving ? "应用中..." : "保存并应用" }}
        </button>
      </footer>
    </section>
  </div>
</template>
