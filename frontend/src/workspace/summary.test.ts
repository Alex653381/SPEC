import assert from "node:assert/strict";
import { test } from "node:test";
import { buildSummary } from "./summary.ts";
import type { Asset, History } from "../types";


function asset(): Asset {
  return {
    id: "stock-1",
    symbol: "000001",
    name: "测试股票",
    asset_type: "stock",
    market: "SZ",
    currency: "CNY",
    provider: "synthetic",
    price_semantics: "close",
    volume_unit: "shares",
    adjustment_mode: "qfq",
    is_active: true,
  };
}


function history(records: Array<Record<string, unknown>>): History {
  return {
    asset_id: "stock-1",
    asset_type: "stock",
    data_class: "daily_bar",
    count: records.length,
    records,
    latest_business_date: String(records[records.length - 1]?.date ?? ""),
  };
}


test("computes range change percentage", () => {
  const summary = buildSummary(
    asset(),
    history([
      { date: "2024-01-02", close: 10 },
      { date: "2024-01-03", close: 11 },
    ]),
    { start: null, end: null },
  );
  assert.equal(summary.firstDate, "2024-01-02");
  assert.equal(summary.lastDate, "2024-01-03");
  assert.equal(summary.count, 2);
  assert.equal(summary.changePct, 10);
});


test("handles empty and invalid base values", () => {
  assert.equal(buildSummary(asset(), history([]), { start: null, end: null }).error, "当前时间范围内无有效数据");
  assert.equal(
    buildSummary(asset(), history([{ date: "2024-01-02", close: 0 }]), { start: null, end: null }).error,
    "基准值必须大于 0",
  );
});
