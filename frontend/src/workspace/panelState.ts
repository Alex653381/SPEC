import type { Asset } from "../types";

export const MAX_PANELS = 6;

export function addPanel(
  panels: Asset[],
  asset: Asset,
  max = MAX_PANELS,
): { panels: Asset[]; added: boolean; reason?: "limit" | "duplicate" } {
  if (panels.length >= max) {
    return { panels, added: false, reason: "limit" };
  }
  if (panels.some((panel) => panel.id === asset.id)) {
    return { panels, added: false, reason: "duplicate" };
  }
  return { panels: [...panels, asset], added: true };
}

export function removePanel(panels: Asset[], assetId: string): Asset[] {
  if (panels.length <= 1) {
    return panels;
  }
  return panels.filter((panel) => panel.id !== assetId);
}
