import { useCallback, useEffect, useMemo, useState } from "react";
import AnalysisPanel from "./AnalysisPanel";
import DataManagementPanel from "./DataManagementPanel";
import { getAssets, getHealth } from "./api/client";
import type { ChartPeriod } from "./charts/aggregate";
import NormalizedComparisonChart from "./charts/NormalizedComparisonChart";
import { computeRange, type RangeKey } from "./charts/normalize";
import type { ZoomWindow } from "./charts/sync";
import {
  DEFAULT_MOVING_AVERAGES,
  type MovingAverageConfig,
} from "./charts/movingAverage";
import type { Asset, Health, History } from "./types";
import AssetPanel from "./workspace/AssetPanel";
import AssetSelector from "./workspace/AssetSelector";
import MovingAverageControl from "./workspace/MovingAverageControl";
import { addPanel, MAX_PANELS, removePanel } from "./workspace/panelState";

const RANGE_OPTIONS: Array<{ key: RangeKey; label: string }> = [
  { key: "1m", label: "近1月" },
  { key: "3m", label: "近3月" },
  { key: "6m", label: "近6月" },
  { key: "1y", label: "近1年" },
  { key: "all", label: "全部" },
];

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [panels, setPanels] = useState<Asset[]>([]);
  const [histories, setHistories] = useState<Record<string, History>>({});
  const [rangeKey, setRangeKey] = useState<RangeKey>("all");
  const [cursorDate, setCursorDate] = useState<string | null>(null);
  const [zoomRange, setZoomRange] = useState<ZoomWindow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [period, setPeriod] = useState<ChartPeriod>("daily");
  const [movingAverages, setMovingAverages] = useState<MovingAverageConfig[]>(
    DEFAULT_MOVING_AVERAGES,
  );

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    getAssets({ limit: 50 })
      .then((data) => {
        if (data.items.length > 0) {
          setPanels((current) => (current.length ? current : [data.items[0]]));
        }
      })
      .catch(() => setNotice("资产目录加载失败"));
  }, []);

  const handleHistory = useCallback((assetId: string, history: History) => {
    setHistories((current) => ({ ...current, [assetId]: history }));
  }, []);

  function handleAdd(asset: Asset) {
    const result = addPanel(panels, asset);
    if (result.added) {
      setPanels(result.panels);
      setNotice(null);
      return;
    }
    setNotice(result.reason === "limit" ? `最多支持 ${MAX_PANELS} 个面板` : "该资产已在面板中");
  }

  function handleRemove(assetId: string) {
    setPanels((current) => removePanel(current, assetId));
    setHistories((current) => {
      const next = { ...current };
      delete next[assetId];
      return next;
    });
  }

  const latestDate = useMemo(
    () =>
      Object.values(histories)
        .map((history) => history.latest_business_date)
        .filter((value): value is string => Boolean(value))
        .sort()
        .slice(-1)[0] ?? new Date().toISOString().slice(0, 10),
    [histories],
  );
  const range = useMemo(() => computeRange(rangeKey, latestDate), [rangeKey, latestDate]);
  const comparisonInputs = useMemo(
    () =>
      panels
        .map((asset) => ({ asset, history: histories[asset.id] }))
        .filter((item): item is { asset: Asset; history: History } => Boolean(item.history)),
    [panels, histories],
  );

  return (
    <div className="app">
      <h1>多资产行情研究</h1>
      <div className="banner">
        当前展示合成/测试数据 · 运行模式 {health?.app_mode ?? "unknown"} · 认证{" "}
        {health?.authentication_implemented ? "已实现" : "未实现"}
      </div>

      <div className="workspace-toolbar">
        <span className="asset-meta">
          面板 {panels.length}/{MAX_PANELS}
        </span>
        <div className="range-switch">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.key}
              className={`filter-button ${rangeKey === option.key ? "active" : ""}`}
              onClick={() => {
                setRangeKey(option.key);
                setZoomRange(null);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="period-switch">
          周期
          <select value={period} onChange={(event) => setPeriod(event.target.value as ChartPeriod)}>
            <option value="daily">日线</option>
            <option value="weekly">周线</option>
            <option value="monthly">月线</option>
          </select>
        </label>
        <MovingAverageControl value={movingAverages} onChange={setMovingAverages} />
        {notice ? <span className="muted">{notice}</span> : null}
      </div>

      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-heading">资产目录</div>
          <AssetSelector onAdd={handleAdd} disabled={panels.length >= MAX_PANELS} />
        </aside>

        <main className="panel-stack">
          {comparisonInputs.length ? (
            <NormalizedComparisonChart
              inputs={comparisonInputs}
              period={period}
              range={range}
              cursorDate={cursorDate}
              onCursorChange={setCursorDate}
              zoomRange={zoomRange}
              onZoomChange={setZoomRange}
            />
          ) : null}

          {panels.length === 0 ? (
            <div className="status">资产目录为空，无法创建面板</div>
          ) : (
            <>
              {panels.map((asset) => (
                <AssetPanel
                  key={asset.id}
                  asset={asset}
                  period={period}
                  movingAverages={movingAverages}
                  removable={panels.length > 1}
                  range={range}
                  onHistory={handleHistory}
                  onRemove={handleRemove}
                  cursorDate={cursorDate}
                  onCursorChange={setCursorDate}
                  zoomRange={zoomRange}
                  onZoomChange={setZoomRange}
                />
              ))}
              <AnalysisPanel assets={panels} />
              <DataManagementPanel />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
