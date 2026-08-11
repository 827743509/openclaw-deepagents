export type DataSourceType = "mysql" | "clickhouse";

export type DataSourceSummary = {
  id: string;
  name: string;
  type: DataSourceType;
  host: string;
  port: number;
  database: string;
  username: string;
  skill_path: string;
  skill_body?: string | null;
};

export type DataSourceConnection = {
  name: string;
  type: DataSourceType;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
};

export type DataSourceCreate = DataSourceConnection & {
  skill_body: string;
};

export type GeneratedSkill = {
  skill_body: string;
  table_count: number;
  column_count: number;
};

const apiUrl = import.meta.env.VITE_SSW_API_URL
  || (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

export async function listDataSources(): Promise<DataSourceSummary[]> {
  const response = await fetch(`${apiUrl}/database/datasources`);
  if (!response.ok) {
    throw new Error(`加载数据源失败：${response.status}`);
  }
  return (await response.json()) as DataSourceSummary[];
}

export async function createDataSource(input: DataSourceCreate): Promise<DataSourceSummary> {
  const response = await fetch(`${apiUrl}/database/datasources/add`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `创建数据源失败：${response.status}`);
  }

  return (await response.json()) as DataSourceSummary;
}

export async function generateDataSourceSkill(input: DataSourceConnection): Promise<GeneratedSkill> {
  const response = await fetch(`${apiUrl}/database/datasources/generate-schema`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `生成 Skill 失败：${response.status}`);
  }

  return (await response.json()) as GeneratedSkill;
}

export async function downloadDataSourceSkill(datasourceId: string): Promise<Blob> {
  const response = await fetch(`${apiUrl}/database/datasources/${datasourceId}/skill`);

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `下载 Skill 失败：${response.status}`);
  }

  return await response.blob();
}

export async function replaceDataSourceSkill(datasourceId: string, file: File): Promise<DataSourceSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${apiUrl}/database/datasources/${datasourceId}/skill/replace`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `替换 Skill 失败：${response.status}`);
  }

  return (await response.json()) as DataSourceSummary;
}

export async function deleteDataSource(datasourceId: string): Promise<void> {
  const response = await fetch(`${apiUrl}/database/datasources/${datasourceId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `删除数据源失败：${response.status}`);
  }
}
