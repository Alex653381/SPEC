import assert from "node:assert/strict";
import test from "node:test";
import { formatPercent, validatePortfolioWeights } from "./portfolio.ts";

test("validates portfolio weights", () => {
  assert.equal(validatePortfolioWeights([]), "组合不能为空");
  assert.equal(validatePortfolioWeights([-1, 101]), "权重必须是非负数字");
  assert.equal(validatePortfolioWeights([40, 50]), "权重合计必须为 100%");
  assert.equal(validatePortfolioWeights([60, 40]), null);
});

test("formats percent values", () => {
  assert.equal(formatPercent(0.1234), "12.34%");
  assert.equal(formatPercent(null), "暂无");
  assert.equal(formatPercent(Number.NaN), "暂无");
});
