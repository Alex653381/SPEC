import assert from "node:assert/strict";
import { test } from "node:test";
import {
  computeRange,
  extractSeries,
  filterHistory,
  normalizeSeries,
  type DateRange,
} from "./normalize.ts";
import type { Asset, History } from "../types";


function asset(id: string, assetType: Asset["asset_type"] = "stock"): Asset {
  return {
    id,
    symbol: id,
    name: id,
    asset_type: assetType,
    market: "SZ",
    currency: "CNY",
    provider: "synthetic",
    price_semantics: assetType === "open_fund" ? "unit_nav" : "close",
    volume_unit: assetType === "open_fund" ? null : "shares",
    adjustment_mode: assetType === "stock" ? "qfq" : null,
    is_active: true,
  };
}


function history(records: Array<Record<string, unknown>>, dataClass: "daily_bar" | "fund_nav" = "daily_bar"): History {
  return {
    asset_id: "a",
    asset_type: dataClass === "fund_nav" ? "open_fund" : "stock",
    data_class: dataClass,
    count: records.length,
    records,
    latest_business_date: records.length ? String(records[records.length - 1].date) : null,
  };
}


test("normalizes from the first in-range valid observation", () => {
  const series = normalizeSeries(
    asset("a"),
    history([
      { date: "2024-01-02", close: 10 },
      { date: "2024-01-03", close: 11 },
      { date: "2024-01-04", close: 9 },
    ]),
    { start: null, end: null },
  );
  assert.equal(series.baseDate, "2024-01-02");
  assert.deepEqual(series.points.map((point) => point.index), [100, 110, 90]);
});


test("different asset scales do not affect each other", () => {
  const low = normalizeSeries(asset("low"), history([{ date: "2024-01-02", close: 2 }, { date: "2024-01-03", close: 4 }]), { start: null, end: null });
  const high = normalizeSeries(asset("high"), history([{ date: "2024-01-02", close: 200 }, { date: "2024-01-03", close: 400 }]), { start: null, end: null });
  assert.deepEqual(low.points.map((p) => p.index), [100, 200]);
  assert.deepEqual(high.points.map((p) => p.index), [100, 200]);
});


test("invalid base values are reported", () => {
  for (const value of [0, -1]) {
    const series = normalizeSeries(asset("a"), history([{ date: "2024-01-02", close: value }]), { start: null, end: null });
    assert.equal(series.error, "基准值必须大于 0");
  }
  for (const value of [Number.NaN, Number.POSITIVE_INFINITY]) {
    const series = normalizeSeries(asset("a"), history([{ date: "2024-01-02", close: value }]), { start: null, end: null });
    assert.equal(series.error, "区间内无有效数据");
  }
});


test("empty and out-of-range series are handled", () => {
  assert.equal(normalizeSeries(asset("a"), history([]), { start: null, end: null }).error, "区间内无有效数据");
  assert.equal(
    normalizeSeries(asset("a"), history([{ date: "2024-01-02", close: 10 }]), { start: "2024-02-01", end: null }).error,
    "区间内无有效数据",
  );
});


test("duplicate dates keep first and invalid dates are ignored", () => {
  const points = extractSeries(
    history([
      { date: "2024-01-02", close: 10 },
      { date: "2024-01-02", close: 99 },
      { date: "bad", close: 5 },
      { date: "2024-01-03", close: 11 },
    ]),
  );
  assert.deepEqual(points, [
    { date: "2024-01-02", value: 10 },
    { date: "2024-01-03", value: 11 },
  ]);
});


test("computeRange uses inclusive local date boundaries", () => {
  assert.deepEqual(computeRange("1m", "2024-01-31"), { start: "2023-12-31", end: "2024-01-31" });
  assert.deepEqual(computeRange("all", "2024-01-31"), { start: null, end: null });
});


test("filterHistory does not mutate input and keeps missing gaps", () => {
  const source = history([
    { date: "2024-01-02", close: 10 },
    { date: "2024-01-04", close: 11 },
  ]);
  const range: DateRange = { start: "2024-01-03", end: null };
  const filtered = filterHistory(source, range);
  assert.equal(source.records.length, 2);
  assert.deepEqual(filtered.records.map((record) => record.date), ["2024-01-04"]);
});
