import assert from "node:assert/strict";
import test from "node:test";
import { aggregateHistory } from "./aggregate.ts";
import type { History } from "../types";

function dailyHistory(records: Array<Record<string, unknown>>): History {
  return {
    asset_id: "stock-000001",
    asset_type: "stock",
    data_class: "daily_bar",
    count: records.length,
    records,
  };
}

test("aggregates daily bars to monthly OHLC and volume", () => {
  const history = dailyHistory([
    { date: "2026-10-09", open: 10, high: 12, low: 9, close: 11, volume: 100, turnover: 1100 },
    { date: "2026-10-12", open: 11, high: 13, low: 10, close: 12, volume: 200, turnover: 2400 },
    { date: "2026-11-02", open: 12, high: 14, low: 11, close: 13, volume: 300, turnover: 3900 },
  ]);
  const monthly = aggregateHistory(history, "monthly");
  assert.equal(monthly.count, 2);
  assert.equal(monthly.records[0].date, "2026-10-12");
  assert.equal(monthly.records[0].open, 10);
  assert.equal(monthly.records[0].high, 13);
  assert.equal(monthly.records[0].low, 9);
  assert.equal(monthly.records[0].close, 12);
  assert.equal(monthly.records[0].volume, 300);
  assert.equal(monthly.records[0].turnover, 3500);
});

test("aggregates weekly bars and keeps latest close", () => {
  const history = dailyHistory([
    { date: "2026-10-05", open: 10, high: 11, low: 9, close: 10, volume: 100 },
    { date: "2026-10-06", open: 10, high: 12, low: 9, close: 11, volume: 150 },
  ]);
  const weekly = aggregateHistory(history, "weekly");
  assert.equal(weekly.count, 1);
  assert.equal(weekly.records[0].date, "2026-10-06");
  assert.equal(weekly.records[0].close, 11);
  assert.equal(weekly.records[0].volume, 250);
});

test("daily period returns original history", () => {
  const history = dailyHistory([{ date: "2026-10-05", open: 10, high: 11, low: 9, close: 10, volume: 100 }]);
  assert.equal(aggregateHistory(history, "daily"), history);
});
