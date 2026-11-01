import type { Asset, History } from "../types";

export type RangeKey = "1m" | "3m" | "6m" | "1y" | "all";

export interface DateRange {
  start: string | null;
  end: string | null;
}

export interface ValuePoint {
  date: string;
  value: number;
}

export interface NormalizedPoint {
  date: string;
  index: number;
  raw: number;
}

export interface NormalizedSeries {
  asset: Asset;
  label: string;
  baseDate: string | null;
  points: NormalizedPoint[];
  error: string | null;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function computeRange(key: RangeKey, latestDate: string): DateRange {
  if (key === "all") {
    return { start: null, end: null };
  }
  const months = key === "1m" ? 1 : key === "3m" ? 3 : key === "6m" ? 6 : 12;
  const end = latestDate;
  const [year, month, day] = end.split("-").map(Number);
  const totalMonths = year * 12 + (month - 1) - months;
  const startYear = Math.floor(totalMonths / 12);
  const startMonth = totalMonths % 12 + 1;
  const lastDay = new Date(startYear, startMonth, 0).getDate();
  const startDay = Math.min(day, lastDay);
  const start = `${String(startYear).padStart(4, "0")}-${String(startMonth).padStart(2, "0")}-${String(startDay).padStart(2, "0")}`;
  return { start, end };
}

export function filterHistory(history: History, range: DateRange): History {
  const records = history.records.filter((record) => {
    if (typeof record.date !== "string") return false;
    if (range.start !== null && record.date < range.start) return false;
    if (range.end !== null && record.date > range.end) return false;
    return true;
  });
  return {
    ...history,
    count: records.length,
    records,
    latest_business_date:
      records.length && typeof records[records.length - 1].date === "string"
        ? (records[records.length - 1].date as string)
        : null,
  };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function extractSeries(history: History): ValuePoint[] {
  const seen = new Set<string>();
  const points: ValuePoint[] = [];
  for (const record of history.records) {
    const value =
      history.data_class === "fund_nav" ? record.unit_nav : record.close;
    if (
      typeof record.date === "string" &&
      DATE_PATTERN.test(record.date) &&
      isFiniteNumber(value)
    ) {
      if (seen.has(record.date)) continue;
      seen.add(record.date);
      points.push({ date: record.date, value });
    }
  }
  points.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return points;
}

export function normalizeSeries(
  asset: Asset,
  history: History,
  range: DateRange,
): NormalizedSeries {
  const label = `${asset.name} (${asset.symbol})`;
  const points = extractSeries(history);
  const inRange = points.filter(
    (point) =>
      (range.start === null || point.date >= range.start) &&
      (range.end === null || point.date <= range.end),
  );
  if (inRange.length === 0) {
    return { asset, label, baseDate: null, points: [], error: "区间内无有效数据" };
  }
  const base = inRange[0];
  if (!(base.value > 0) || !Number.isFinite(base.value)) {
    return { asset, label, baseDate: null, points: [], error: "基准值必须大于 0" };
  }
  return {
    asset,
    label,
    baseDate: base.date,
    points: inRange.map((point) => ({
      date: point.date,
      raw: point.value,
      index: Number(((point.value / base.value) * 100).toFixed(4)),
    })),
    error: null,
  };
}
