export interface MovingAverageConfig {
  id: string;
  period: number;
  enabled: boolean;
}

export const MOVING_AVERAGE_LIMITS = {
  min: 1,
  max: 250,
} as const;

export const MOVING_AVERAGE_COLORS = ["#f2b84b", "#8d7bff", "#49c0a8"] as const;

export const DEFAULT_MOVING_AVERAGES: MovingAverageConfig[] = [
  { id: "ma-5", period: 5, enabled: true },
  { id: "ma-20", period: 20, enabled: false },
  { id: "ma-60", period: 60, enabled: false },
];

export function clampMovingAveragePeriod(value: number): number {
  if (!Number.isFinite(value)) return MOVING_AVERAGE_LIMITS.min;
  const rounded = Math.round(value);
  return Math.min(
    MOVING_AVERAGE_LIMITS.max,
    Math.max(MOVING_AVERAGE_LIMITS.min, rounded),
  );
}

export function computeMovingAverage(
  values: number[],
  period: number,
): Array<number | null> {
  const window = clampMovingAveragePeriod(period);
  const result: Array<number | null> = new Array(values.length).fill(null);
  let sum = 0;

  for (let index = 0; index < values.length; index += 1) {
    sum += values[index];
    if (index >= window) {
      sum -= values[index - window];
    }
    if (index >= window - 1) {
      result[index] = sum / window;
    }
  }

  return result;
}
