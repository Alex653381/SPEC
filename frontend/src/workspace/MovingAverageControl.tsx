import type { MovingAverageConfig } from "../charts/movingAverage";
import { MOVING_AVERAGE_LIMITS, clampMovingAveragePeriod } from "../charts/movingAverage";

interface MovingAverageControlProps {
  value: MovingAverageConfig[];
  onChange: (value: MovingAverageConfig[]) => void;
}

function updateConfig(
  rows: MovingAverageConfig[],
  id: string,
  update: (row: MovingAverageConfig) => MovingAverageConfig,
): MovingAverageConfig[] {
  return rows.map((row) => (row.id === id ? update(row) : row));
}

export default function MovingAverageControl({
  value,
  onChange,
}: MovingAverageControlProps) {
  function changePeriod(id: string, raw: string) {
    const parsed = Number(raw);
    if (raw.trim() === "" || !Number.isFinite(parsed)) return;
    onChange(
      updateConfig(value, id, (row) => ({
        ...row,
        period: clampMovingAveragePeriod(parsed),
      })),
    );
  }

  function toggle(id: string) {
    onChange(
      updateConfig(value, id, (row) => ({
        ...row,
        enabled: !row.enabled,
      })),
    );
  }

  return (
    <details className="ma-dropdown">
      <summary className="ma-trigger">
        均线
        <span className="ma-caret" aria-hidden="true" />
      </summary>
      <div className="ma-menu">
        {value.map((row) => (
          <div className="ma-option" key={row.id}>
            <label className="ma-period-field">
              <input
                type="number"
                min={MOVING_AVERAGE_LIMITS.min}
                max={MOVING_AVERAGE_LIMITS.max}
                step={1}
                value={row.period}
                onChange={(event) => changePeriod(row.id, event.target.value)}
              />
              <span>日均线</span>
            </label>
            <button
              type="button"
              role="switch"
              aria-checked={row.enabled}
              aria-label={`${row.period}日均线`}
              className={`ma-switch ${row.enabled ? "on" : ""}`}
              onClick={() => toggle(row.id)}
            >
              <span className="ma-switch-knob" />
            </button>
          </div>
        ))}
      </div>
    </details>
  );
}
