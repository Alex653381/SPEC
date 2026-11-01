import type { AssetType } from "../types";

export const TYPE_LABELS: Record<AssetType, string> = {
  stock: "股票",
  index: "指数",
  etf: "ETF",
  open_fund: "场外基金",
};
