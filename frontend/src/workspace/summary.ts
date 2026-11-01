import { extractSeries, type DateRange } from "../charts/normalize.ts";
import type { Asset, History } from "../types";
import { TYPE_LABELS } from "./labels.ts";

export interface Summary {
  assetName: string;
  assetCode: string;
  assetTypeLabel: string;
  metricLabel: string;
  firstDate: string | null;
  lastDate: string | null;
  count: number;
  changePct: number | null;
  error: string | null;
}

export function buildSummary(asset: Asset, history: History, range: DateRange): Summary {
  const metricLabel =
    history.data_class === "fund_nav" ? "单位净值变化" : "价格变化";
  const points = extractSeries(history).filter(
    (point) =>
      (range.start === null || point.date >= range.start) &&
      (range.end === null || point.date <= range.end),
  );

  if (points.length === 0) {
    return {
      assetName: asset.name,
      assetCode: asset.symbol,
      assetTypeLabel: TYPE_LABELS[asset.asset_type],
      metricLabel,
      firstDate: null,
      lastDate: null,
      count: 0,
      changePct: null,
      error: "当前时间范围内无有效数据",
    };
  }

  const first = points[0];
  const last = points[points.length - 1];
  if (!(first.value > 0) || !Number.isFinite(first.value)) {
    return {
      assetName: asset.name,
      assetCode: asset.symbol,
      assetTypeLabel: TYPE_LABELS[asset.asset_type],
      metricLabel,
      firstDate: first.date,
      lastDate: last.date,
      count: points.length,
      changePct: null,
      error: "基准值必须大于 0",
    };
  }

  return {
    assetName: asset.name,
    assetCode: asset.symbol,
    assetTypeLabel: TYPE_LABELS[asset.asset_type],
    metricLabel,
    firstDate: first.date,
    lastDate: last.date,
    count: points.length,
    changePct: Number((((last.value - first.value) / first.value) * 100).toFixed(2)),
    error: null,
  };
}
