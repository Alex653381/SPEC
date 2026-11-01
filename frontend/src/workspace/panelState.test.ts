import assert from "node:assert/strict";
import { test } from "node:test";
import { addPanel, MAX_PANELS, removePanel } from "./panelState.ts";
import type { Asset } from "../types";


function asset(id: string): Asset {
  return {
    id,
    symbol: id,
    name: id,
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


test("adds unique panels up to the limit", () => {
  const base = Array.from({ length: MAX_PANELS - 1 }, (_, index) => asset(`a${index}`));
  const added = addPanel(base, asset("last"));
  assert.equal(added.added, true);
  assert.equal(added.panels.length, MAX_PANELS);
});


test("rejects duplicate and limit", () => {
  const base = [asset("a0")];
  assert.equal(addPanel(base, asset("a0")).reason, "duplicate");
  const full = Array.from({ length: MAX_PANELS }, (_, index) => asset(`a${index}`));
  assert.equal(addPanel(full, asset("extra")).reason, "limit");
});


test("keeps at least one panel on removal", () => {
  assert.equal(removePanel([asset("only")], "only").length, 1);
  assert.equal(removePanel([asset("a"), asset("b")], "a").length, 1);
});
