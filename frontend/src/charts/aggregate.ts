import type { History } from "../types";

export type ChartPeriod = "daily" | "weekly" | "monthly";

type Row = Record<string, unknown>;

function localDateKey(value: string): { year: number; month: number; day: number } {
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

function formatDate(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function weekKey(value: string): string {
  const { year, month, day } = localDateKey(value);
  const date = new Date(year, month - 1, day);
  const mondayOffset = (date.getDay() + 6) % 7;
  const monday = new Date(year, month - 1, day - mondayOffset);
  return formatDate(monday.getFullYear(), monday.getMonth() + 1, monday.getDate());
}

function monthKey(value: string): string {
  return value.slice(0, 7);
}

function periodKey(period: ChartPeriod, date: string): string {
  if (period === "daily") return date;
  if (period === "weekly") return weekKey(date);
  return monthKey(date);
}

function numberValue(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function aggregateDaily(records: Row[], period: ChartPeriod): Row[] {
  const groups = new Map<string, Row & { _last: string; _open: number; _high: number; _low: number; _close: number; _volume: number; _turnoverSum: number; _turnoverCount: number }>();

  for (const record of records) {
    const date = String(record.date ?? "");
    if (!date) continue;
    const key = periodKey(period, date);
    let group = groups.get(key);
    if (!group) {
      group = {
        ...record,
        _last: date,
        _open: numberValue(record.open),
        _high: numberValue(record.high),
        _low: numberValue(record.low),
        _close: numberValue(record.close),
        _volume: 0,
        _turnoverSum: 0,
        _turnoverCount: 0,
      };
      groups.set(key, group);
    }
    if (date > group._last) group._last = date;
    group._high = Math.max(group._high, numberValue(record.high));
    group._low = Math.min(group._low, numberValue(record.low));
    group._close = numberValue(record.close);
    group._volume += numberValue(record.volume);
    const turnover = Number(record.turnover);
    if (Number.isFinite(turnover)) {
      group._turnoverSum += turnover;
      group._turnoverCount += 1;
    }
  }

  return Array.from(groups.values())
    .sort((a, b) => (a._last < b._last ? -1 : a._last > b._last ? 1 : 0))
    .map((group) => ({
      ...group,
      date: group._last,
      open: group._open,
      high: group._high,
      low: group._low,
      close: group._close,
      volume: group._volume,
      turnover: group._turnoverCount > 0 ? group._turnoverSum : null,
    }));
}

function aggregateFund(records: Row[], period: ChartPeriod): Row[] {
  const groups = new Map<string, Row>();
  for (const record of records) {
    const date = String(record.date ?? "");
    if (!date) continue;
    const key = periodKey(period, date);
    const existing = groups.get(key);
    if (!existing || date > String(existing.date ?? "")) {
      groups.set(key, { ...record, date });
    }
  }
  return Array.from(groups.values()).sort((a, b) =>
    String(a.date) < String(b.date) ? -1 : String(a.date) > String(b.date) ? 1 : 0,
  );
}

export function aggregateHistory(history: History, period: ChartPeriod): History {
  if (period === "daily" || history.count === 0) {
    return history;
  }
  const records =
    history.data_class === "fund_nav"
      ? aggregateFund(history.records, period)
      : aggregateDaily(history.records, period);
  return {
    ...history,
    count: records.length,
    records,
    latest_business_date:
      records.length > 0 ? String(records[records.length - 1].date) : null,
  };
}
