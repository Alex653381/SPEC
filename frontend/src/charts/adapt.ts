import type { History } from "../types";

export type ChartSpec =
  | {
      kind: "candlestick";
      dates: string[];
      candles: [number, number, number, number][];
      volumes: number[];
    }
  | {
      kind: "line";
      dates: string[];
      values: number[];
      valueName: string;
    };

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function adaptHistory(history: History): ChartSpec | null {
  if (history.data_class === "fund_nav") {
    const dates: string[] = [];
    const values: number[] = [];
    for (const record of history.records) {
      if (typeof record.date === "string" && isNumber(record.unit_nav)) {
        dates.push(record.date);
        values.push(record.unit_nav);
      }
    }
    return dates.length ? { kind: "line", dates, values, valueName: "单位净值" } : null;
  }

  const dates: string[] = [];
  const candles: [number, number, number, number][] = [];
  const volumes: number[] = [];
  for (const record of history.records) {
    const { date, open, high, low, close, volume } = record;
    if (
      typeof date === "string" &&
      isNumber(open) &&
      isNumber(high) &&
      isNumber(low) &&
      isNumber(close)
    ) {
      dates.push(date);
      candles.push([open, close, low, high]);
      volumes.push(isNumber(volume) ? volume : 0);
    }
  }
  return dates.length ? { kind: "candlestick", dates, candles, volumes } : null;
}
