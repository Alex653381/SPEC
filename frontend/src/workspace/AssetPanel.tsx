import { useEffect, useMemo, useState } from "react";
import { getHistory } from "../api/client";
import HistoryChart from "../charts/HistoryChart";
import { filterHistory, type DateRange } from "../charts/normalize";
import type { ZoomWindow } from "../charts/sync";
import type { Asset, History } from "../types";
import { TYPE_LABELS } from "./labels";
import { buildSummary } from "./summary";

interface AssetPanelProps {
  asset: Asset;
  removable: boolean;
  range: DateRange;
  onHistory: (assetId: string, history: History) => void;
  onRemove: (assetId: string) => void;
  cursorDate?: string | null;
  onCursorChange?: (date: string | null) => void;
  zoomRange?: ZoomWindow | null;
  onZoomChange?: (range: ZoomWindow | null) => void;
}

export default function AssetPanel({
  asset,
  removable,
  range,
  onHistory,
  onRemove,
  cursorDate = null,
  onCursorChange,
  zoomRange = null,
  onZoomChange,
}: AssetPanelProps) {
  const [history, setHistory] = useState<History | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setHistory(null);

    getHistory(asset.id, { limit: 500 }, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setHistory(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [asset.id, retryKey]);

  useEffect(() => {
    if (history) onHistory(asset.id, history);
  }, [asset.id, history, onHistory]);

  const displayHistory = useMemo(
    () => (history ? filterHistory(history, range) : null),
    [history, range],
  );
  const summary = useMemo(
    () => (displayHistory ? buildSummary(asset, displayHistory, range) : null),
    [asset, displayHistory, range],
  );

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <div className="asset-name">{asset.name}</div>
          <div className="asset-meta">
            {asset.symbol} · {TYPE_LABELS[asset.asset_type]} · {asset.market}
          </div>
        </div>
        {removable ? (
          <button className="remove-button" onClick={() => onRemove(asset.id)}>
            移除
          </button>
        ) : null}
      </header>

      {loading ? (
        <div className="status">加载中…</div>
      ) : error ? (
        <div className="status">
          {error}
          <button className="asset-button" onClick={() => setRetryKey((key) => key + 1)}>
            重试
          </button>
        </div>
      ) : displayHistory && displayHistory.count > 0 ? (
        <>
          {summary ? (
            <div className="summary">
              <span>{summary.firstDate ?? "-"} 至 {summary.lastDate ?? "-"}</span>
              <span>
                {summary.metricLabel}
                {summary.changePct === null ? "：暂无有效数据" : `：${summary.changePct.toFixed(2)}%`}
              </span>
              <span>有效观测 {summary.count} 条</span>
            </div>
          ) : null}
          <HistoryChart
            history={displayHistory}
            cursorDate={cursorDate}
            onCursorChange={onCursorChange}
            zoomRange={zoomRange}
            onZoomChange={onZoomChange}
          />
        </>
      ) : (
        <div className="status">当前时间范围内无历史数据</div>
      )}
    </section>
  );
}
