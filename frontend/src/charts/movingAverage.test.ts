import assert from "node:assert/strict";
import test from "node:test";
import {
  clampMovingAveragePeriod,
  computeMovingAverage,
  MOVING_AVERAGE_LIMITS,
} from "./movingAverage.ts";

test("computes a simple moving average with leading nulls", () => {
  assert.deepEqual(computeMovingAverage([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
});

test("periods larger than the series stay null", () => {
  assert.deepEqual(computeMovingAverage([1, 2, 3], 5), [null, null, null]);
});

test("clamps moving average periods to the configured range", () => {
  assert.equal(clampMovingAveragePeriod(0), MOVING_AVERAGE_LIMITS.min);
  assert.equal(clampMovingAveragePeriod(999), MOVING_AVERAGE_LIMITS.max);
  assert.equal(clampMovingAveragePeriod(20.4), 20);
});
