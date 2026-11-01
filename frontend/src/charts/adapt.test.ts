import assert from "node:assert/strict";
import { test } from "node:test";
import { adaptHistory } from "./adapt.ts";
import type { History } from "../types";


test("fund nav adapts to a line series without OHLC", () => {
  const history: History = {
    asset_id: "fund-110022",
    asset_type: "open_fund",
    data_class: "fund_nav",
    count: 2,
    records: [
      { date: "2024-01-02", unit_nav: 1.5 },
      { date: "2024-01-03", unit_nav: 1.52 },
    ],
  };
  const spec = adaptHistory(history);
  assert.ok(spec);
  assert.equal(spec.kind, "line");
  assert.deepEqual(spec.dates, ["2024-01-02", "2024-01-03"]);
});


test("daily bar adapts to candlestick with volumes", () => {
  const history: History = {
    asset_id: "index-000001",
    asset_type: "index",
    data_class: "daily_bar",
    count: 1,
    records: [
      { date: "2024-01-02", open: 3000, high: 3010, low: 2990, close: 3005, volume: 1000000, turnover: null },
    ],
  };
  const spec = adaptHistory(history);
  assert.ok(spec);
  assert.equal(spec.kind, "candlestick");
  assert.deepEqual(spec.candles[0], [3000, 3005, 2990, 3010]);
});


test("empty history returns null", () => {
  const history: History = {
    asset_id: "stock-000001",
    asset_type: "stock",
    data_class: "daily_bar",
    count: 0,
    records: [],
  };
  assert.equal(adaptHistory(history), null);
});
