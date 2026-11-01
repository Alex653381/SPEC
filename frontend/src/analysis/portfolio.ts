export function validatePortfolioWeights(weights: number[]): string | null {
  if (weights.length === 0) return "组合不能为空";
  if (weights.some((weight) => !Number.isFinite(weight) || weight < 0)) {
    return "权重必须是非负数字";
  }
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  if (Math.abs(total - 100) > 0.01) {
    return "权重合计必须为 100%";
  }
  return null;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "暂无";
  }
  return `${(value * 100).toFixed(2)}%`;
}
