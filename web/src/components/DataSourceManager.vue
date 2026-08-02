<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  Database,
  Download,
  FileText,
  Plus,
  RefreshCcw,
  Save,
  Trash2,
} from "@lucide/vue";
import {
  type DataSourceConnection,
  type DataSourceSummary,
  type DataSourceType,
  createDataSource,
  deleteDataSource,
  downloadDataSourceSkill,
  generateDataSourceSkill,
  listDataSources,
} from "../services/datasources";
import type { SidebarView } from "./AppSidebar.vue";

const props = defineProps<{
  view: Extract<SidebarView, "datasource-list" | "datasource-create">;
}>();

const emit = defineEmits<{
  navigate: [view: SidebarView];
}>();

const datasources = ref<DataSourceSummary[]>([]);
const isLoading = ref(false);
const isGenerating = ref(false);
const isSaving = ref(false);
const errorText = ref("");
const successText = ref("");
const generatedStats = ref("");
const form = ref<DataSourceConnection>({
  name: "",
  type: "mysql",
  host: "",
  port: 3306,
  database: "",
  username: "",
  password: "",
});
const skillBody = ref("");

const isListView = computed(() => props.view === "datasource-list");
const formReady = computed(() => (
  Boolean(form.value.name.trim())
  && Boolean(form.value.host.trim())
  && Boolean(form.value.database.trim())
  && Boolean(form.value.username.trim())
  && form.value.port > 0
));
const canSave = computed(() => formReady.value && Boolean(skillBody.value.trim()) && !isSaving.value);

watch(() => form.value.type, (type) => {
  form.value.port = type === "mysql" ? 3306 : 8123;
});

onMounted(() => {
  void refreshDatasources();
});

async function refreshDatasources(): Promise<void> {
  isLoading.value = true;
  errorText.value = "";
  try {
    datasources.value = await listDataSources();
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "加载数据源失败";
  } finally {
    isLoading.value = false;
  }
}

async function generateSkill(): Promise<void> {
  if (!formReady.value || isGenerating.value) {
    return;
  }

  isGenerating.value = true;
  errorText.value = "";
  successText.value = "";
  generatedStats.value = "";
  try {
    const generated = await generateDataSourceSkill(form.value);
    skillBody.value = generated.skill_body;
    generatedStats.value = `已读取 ${generated.table_count} 张表、${generated.column_count} 个字段`;
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "生成 Skill 失败";
  } finally {
    isGenerating.value = false;
  }
}

async function saveDatasource(): Promise<void> {
  if (!canSave.value) {
    return;
  }

  isSaving.value = true;
  errorText.value = "";
  successText.value = "";
  try {
    await createDataSource({
      ...form.value,
      skill_body: skillBody.value,
    });
    successText.value = "数据源已保存";
    resetForm();
    await refreshDatasources();
    emit("navigate", "datasource-list");
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存数据源失败";
  } finally {
    isSaving.value = false;
  }
}

function resetForm(): void {
  form.value = {
    name: "",
    type: "mysql",
    host: "",
    port: 3306,
    database: "",
    username: "",
    password: "",
  };
  skillBody.value = "";
  generatedStats.value = "";
}

async function removeDatasource(datasource: DataSourceSummary): Promise<void> {
  if (!window.confirm(`确认删除数据源「${datasource.name}」吗？`)) {
    return;
  }

  errorText.value = "";
  successText.value = "";
  try {
    await deleteDataSource(datasource.id);
    successText.value = "数据源已删除";
    await refreshDatasources();
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "删除数据源失败";
  }
}

async function downloadSkill(datasource: DataSourceSummary): Promise<void> {
  errorText.value = "";
  try {
    const blob = await downloadDataSourceSkill(datasource.id);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${datasource.id}-SKILL.md`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "下载 Skill 失败";
  }
}

function typeLabel(type: DataSourceType): string {
  return type === "mysql" ? "MySQL" : "ClickHouse";
}
</script>

<template>
  <section class="manager-page" aria-label="text_to_sql 数据源管理">
    <header class="manager-header">
      <div>
        <p class="eyebrow">text_to_sql</p>
        <h2>{{ isListView ? "数据源管理" : "新增数据源" }}</h2>
      </div>
      <div class="manager-actions">
        <button
          v-if="isListView"
          class="icon-button"
          type="button"
          title="刷新"
          :disabled="isLoading"
          @click="refreshDatasources"
        >
          <RefreshCcw :size="19" />
        </button>
        <button
          class="secondary-button"
          type="button"
          @click="emit('navigate', isListView ? 'datasource-create' : 'datasource-list')"
        >
          <Plus v-if="isListView" :size="18" />
          <Database v-else :size="18" />
          {{ isListView ? "新增数据源" : "返回列表" }}
        </button>
      </div>
    </header>

    <p v-if="errorText" class="inline-error">{{ errorText }}</p>
    <p v-if="successText" class="inline-success">{{ successText }}</p>

    <div v-if="isListView" class="datasource-list-page">
      <article v-for="datasource in datasources" :key="datasource.id" class="datasource-card">
        <div class="datasource-card-main">
          <div class="datasource-icon">
            <Database :size="20" />
          </div>
          <div>
            <strong>{{ datasource.name }}</strong>
            <small>
              {{ typeLabel(datasource.type) }} · {{ datasource.host }}:{{ datasource.port }} / {{ datasource.database }}
            </small>
            <span>{{ datasource.skill_path }}</span>
          </div>
        </div>
        <div class="datasource-card-actions">
          <button class="icon-button" type="button" title="下载 Skill" @click="downloadSkill(datasource)">
            <Download :size="18" />
          </button>
          <button class="icon-button danger" type="button" title="删除数据源" @click="removeDatasource(datasource)">
            <Trash2 :size="18" />
          </button>
        </div>
      </article>

      <p v-if="isLoading" class="history-empty">加载数据源中</p>
      <p v-else-if="!datasources.length" class="empty-state">暂时没有 text_to_sql 数据源</p>
    </div>

    <form v-else class="datasource-editor" @submit.prevent="saveDatasource">
      <div class="field-grid">
        <label class="field-label">
          <span>名称</span>
          <input v-model.trim="form.name" placeholder="如：订单库" />
        </label>
        <label class="field-label">
          <span>数据库类型</span>
          <select v-model="form.type">
            <option value="mysql">MySQL</option>
            <option value="clickhouse">ClickHouse</option>
          </select>
        </label>
      </div>

      <div class="field-grid">
        <label class="field-label">
          <span>Host</span>
          <input v-model.trim="form.host" placeholder="127.0.0.1" />
        </label>
        <label class="field-label">
          <span>Port</span>
          <input v-model.number="form.port" type="number" min="1" max="65535" />
        </label>
      </div>

      <div class="field-grid">
        <label class="field-label">
          <span>Database</span>
          <input v-model.trim="form.database" placeholder="database" />
        </label>
        <label class="field-label">
          <span>Username</span>
          <input v-model.trim="form.username" placeholder="username" />
        </label>
      </div>

      <label class="field-label">
        <span>Password</span>
        <input v-model="form.password" type="password" autocomplete="new-password" />
      </label>

      <div class="form-actions">
        <button class="secondary-button" type="button" :disabled="!formReady || isGenerating" @click="generateSkill">
          <FileText :size="18" />
          {{ isGenerating ? "生成中" : "生成 Skill" }}
        </button>
        <button class="secondary-button" type="submit" :disabled="!canSave">
          <Save :size="18" />
          {{ isSaving ? "保存中" : "保存数据源" }}
        </button>
      </div>

      <p v-if="generatedStats" class="inline-success">{{ generatedStats }}</p>

      <label class="field-label">
        <span>Skill Markdown 正文</span>
        <textarea v-model="skillBody" rows="12" placeholder="可先生成，也可以手动粘贴 Skill 正文"></textarea>
      </label>
    </form>
  </section>
</template>
