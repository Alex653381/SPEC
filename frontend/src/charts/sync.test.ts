import assert from "node:assert/strict";
import { test } from "node:test";
import { dateToIndex, visibleDates, zoomPercentFor } from "./sync.ts";


test("maps dates to indices without relying on position", () => {
  assert.equal(dateToIndex(["2024-01-02", "2024-01-04", "2024-01-05"], "2024-01-04"), 1);
  assert.equal(dateToIndex(["2024-01-02"], "2024-01-04"), -1);
  assert.equal(dateToIndex([], null), -1);
});


test("converts a date window to zoom percentages", () => {
  const dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"];
  assert.deepEqual(zoomPercentFor(dates, { start: "2024-01-03", end: "2024-01-04" }), {
    start: (1 / 3) * 100,
    end: (2 / 3) * 100,
  });
  assert.deepEqual(zoomPercentFor([], { start: null, end: null }), { start: 0, end: 100 });
});


test("derives visible dates from percentages", () => {
  const dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"];
  assert.deepEqual(visibleDates(dates, (1 / 3) * 100, (2 / 3) * 100), {
    start: "2024-01-03",
    end: "2024-01-04",
  });
  assert.deepEqual(visibleDates([], 0, 100), { start: null, end: null });
});
