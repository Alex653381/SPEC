export type AssetType = "stock" | "index" | "etf" | "open_fund";

export interface Asset {
  id: string;
  symbol: string;
  name: string;
  asset_type: AssetType;
  market: string;
  currency: string;
  provider: string;
  price_semantics: string;
  volume_unit?: string | null;
  adjustment_mode?: string | null;
  is_active: boolean;
}

export interface AssetList {
  items: Asset[];
  total: number;
  limit: number;
  offset: number;
}

export interface Health {
  status: string;
  app_mode: string;
  database: string;
  authentication_implemented: boolean;
}

export interface History {
  asset_id: string;
  asset_type: AssetType;
  data_class: "daily_bar" | "fund_nav";
  start_date?: string | null;
  end_date?: string | null;
  latest_business_date?: string | null;
  count: number;
  records: Array<Record<string, unknown>>;
}

export interface DrawdownInfo {
  peak_date: string;
  trough_date: string;
  drawdown: number;
}

export interface AssetMetrics {
  asset_id: string;
  asset_type: AssetType;
  metric: "close" | "unit_nav";
  price_semantics: string;
  adjustment_mode?: string | null;
  provider: string;
  source: string;
  first_date?: string | null;
  last_date?: string | null;
  count: number;
  cumulative_return?: number | null;
  annualized_return?: number | null;
  annualized_volatility?: number | null;
  return_risk_ratio?: number | null;
  max_drawdown?: DrawdownInfo | null;
  return_series: Array<{ date: string; cumulative_return: number }>;
  notes: string[];
  error?: string | null;
}

export interface CompareResult {
  asset_id: string;
  benchmark_asset_id: string;
  asset_metric: string;
  benchmark_metric: string;
  asset_source: string;
  benchmark_source: string;
  count: number;
  start_date?: string | null;
  end_date?: string | null;
  asset_cumulative_return?: number | null;
  benchmark_cumulative_return?: number | null;
  excess_return?: number | null;
  normalized: {
    asset: Array<{ date: string; value: number }>;
    benchmark: Array<{ date: string; value: number }>;
  };
  error?: string | null;
}

export interface PortfolioResult {
  count: number;
  start_date?: string | null;
  end_date?: string | null;
  cumulative_return?: number | null;
  max_drawdown?: DrawdownInfo | null;
  annualized_volatility?: number | null;
  contributions: Array<{ asset_id: string; contribution: number }>;
  curve: Array<{ date: string; cumulative_return: number }>;
  error?: string | null;
}

export interface DataStatus {
  asset_id: string;
  asset_type: AssetType;
  provider: string;
  source: string;
  data_class: "daily_bar" | "fund_nav";
  record_count: number;
  first_date?: string | null;
  last_date?: string | null;
  duplicate_dates: string[];
  calendar_days: number;
  assessment: string;
  quality_status?: "empty" | "normal" | "warning" | "error";
  quality_issue_count?: number;
  quality_by_severity?: { error?: number; warning?: number; info?: number };
  messages: string[];
}

export interface DataStatusList {
  items: DataStatus[];
}

export interface UpdatePlan {
  asset_type: AssetType;
  asset_code: string;
  database: string;
  latest_date?: string | null;
  window?: { start: string; end: string } | null;
}

export interface UpdateJob {
  id: string;
  asset_type: AssetType;
  status: "running" | "success" | "failed";
  result?: {
    status?: string;
    error_category?: string;
    error_summary?: string;
    execution_summary?: Record<string, unknown>;
    [key: string]: unknown;
  } | null;
}

export interface RegisterResult {
  status: string;
  asset_type: string;
  asset_id?: string;
  provider?: string;
  fetched_rows?: number;
  converted_rows?: number;
  quality_issue_count?: number;
  inserted?: number;
  skipped?: number;
  conflicts?: number;
  database_written?: boolean;
  committed?: boolean;
}
