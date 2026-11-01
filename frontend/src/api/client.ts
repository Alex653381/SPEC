import type {
  Asset,
  AssetList,
  AssetMetrics,
  AssetType,
  CompareResult,
  DataStatusList,
  Health,
  History,
  PortfolioResult,
  RegisterResult,
  UpdateJob,
  UpdatePlan,
} from "../types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    let code = "REQUEST_FAILED";
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      // 保留默认错误信息。
    }
    throw new Error(`${code}: ${message}`);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/health");
}

export function getAssets(params: {
  asset_type?: AssetType;
  q?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<AssetList> {
  const query = new URLSearchParams();
  if (params.asset_type) query.set("asset_type", params.asset_type);
  if (params.q) query.set("q", params.q);
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<AssetList>(`/assets${suffix}`);
}

export function getAsset(assetId: string): Promise<Asset> {
  return request<Asset>(`/assets/${encodeURIComponent(assetId)}`);
}

export function getHistory(
  assetId: string,
  params: { start_date?: string; end_date?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<History> {
  const query = new URLSearchParams();
  if (params.start_date) query.set("start_date", params.start_date);
  if (params.end_date) query.set("end_date", params.end_date);
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<History>(`/assets/${encodeURIComponent(assetId)}/history${suffix}`, { signal });
}

export function getAssetMetrics(
  assetId: string,
  params: { start_date?: string; end_date?: string } = {},
  signal?: AbortSignal,
): Promise<AssetMetrics> {
  const query = new URLSearchParams();
  if (params.start_date) query.set("start_date", params.start_date);
  if (params.end_date) query.set("end_date", params.end_date);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<AssetMetrics>(
    `/analysis/assets/${encodeURIComponent(assetId)}/metrics${suffix}`,
    { signal },
  );
}

export function compareAssets(body: {
  asset_id: string;
  benchmark_asset_id: string;
  start_date?: string;
  end_date?: string;
}): Promise<CompareResult> {
  return request<CompareResult>("/analysis/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function analyzePortfolio(body: {
  items: Array<{ asset_id: string; weight: number }>;
  start_date?: string;
  end_date?: string;
}): Promise<PortfolioResult> {
  return request<PortfolioResult>("/analysis/portfolio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getDataStatus(): Promise<DataStatusList> {
  return request<DataStatusList>("/data-status");
}

export function preflightUpdate(body: {
  asset_type: AssetType;
  start_date?: string;
  end_date?: string;
}): Promise<UpdatePlan> {
  return request<UpdatePlan>("/admin/update/preflight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function runUpdate(body: {
  asset_type: AssetType;
  start_date: string;
  end_date: string;
}): Promise<UpdateJob> {
  return request<UpdateJob>("/admin/update/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getUpdateJob(jobId: string): Promise<UpdateJob> {
  return request<UpdateJob>(`/admin/update/jobs/${encodeURIComponent(jobId)}`);
}

export function registerAsset(body: {
  asset_type: AssetType;
  code: string;
  name?: string;
  market?: string;
  start_date: string;
  end_date: string;
  confirm: boolean;
}): Promise<RegisterResult> {
  return request<RegisterResult>("/admin/assets/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function expandAsset(body: {
  asset_type: AssetType;
  code: string;
  start_date: string;
  end_date: string;
  confirm: boolean;
}): Promise<RegisterResult> {
  return request<RegisterResult>("/admin/assets/expand", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
