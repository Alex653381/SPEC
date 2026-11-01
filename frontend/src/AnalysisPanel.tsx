import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { analyzePortfolio, compareAssets, getAssetMetrics } from "./api/client";
import { formatPercent, validatePortfolioWeights } from "./analysis/portfolio";
import type { Asset, AssetMetrics, CompareResult, PortfolioResult } from "./types";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

interface AnalysisPanelProps {
  assets: Asset[];
}

export default function AnalysisPanel({ assets }: AnalysisPanelProps) {
  const [assetId, setAssetId] = useState(assets[0]?.id ?? "");
  const [benchmarkId, setBenchmarkId] = useState(assets[1]?.id ?? assets[0]?.id ?? "");
  const [metrics, setMetrics] = useState<AssetMetrics | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [portfolio, setPortfolio] = useState<PortfolioResult | null>(null);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);

  useEffect(() => {
    if (!assetId) return;
    const controller = new AbortController();
    setMetricsLoading(true);
    setMetricsError(null);
    setMetrics(null);
    getAssetMetrics(assetId, {}, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setMetrics(data);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMetricsError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMetricsLoading(false);
      });
    return () => controller.abort();
  }, [assetId]);

  function runCompare() {
    if (!assetId || !benchmarkId) return;
    setCompareLoading(true);
    setCompareError(null);
    setCompare(null);
    compareAssets({ asset_id: assetId, benchmark_asset_id: benchmarkId })
      .then(setCompare)
      .catch((error: unknown) =>
        setCompareError(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => setCompareLoading(false));
  }

  function runPortfolio() {
    const items = assets.map((asset) => ({
      asset_id: asset.id,
      weight: Number(weights[asset.id] ?? 0),
    }));
    const validationError = validatePortfolioWeights(items.map((item) => item.weight));
    if (validationError) {
      setPortfolioError(validationError);
      setPortfolio(null);
      return;
    }
    setPortfolioLoading(true);
    setPortfolioError(null);
    setPortfolio(null);
    analyzePortfolio({ items })
      .then(setPortfolio)
      .catch((error: unknown) =>
        setPortfolioError(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => setPortfolioLoading(false));
  }

  const compareChart = useMemo(() => {
    if (!compare || compare.error) return null;
    const dates = Array.from(
      new Set([
        ...compare.normalized.asset.map((point) => point.date),
        ...compare.normalized.benchmark.map((point) => point.date),
      ]),
    ).sort();
    const assetIndex = new Map(compare.normalized.asset.map((point) => [point.date, point.value]));
    const benchmarkIndex = new Map(
      compare.normalized.benchmark.map((point) => [point.date, point.value]),
    );
    return {
      dates,
      series: [
        { name: "资产", data: dates.map((date) => assetIndex.get(date) ?? null) },
        { name: "基准", data: dates.map((date) => benchmarkIndex.get(date) ?? null) },
      ],
    };
  }, [compare]);

  const portfolioChart = useMemo(() => {
    if (!portfolio || portfolio.error || portfolio.curve.length === 0) return null;
    return {
      dates: portfolio.curve.map((point) => point.date),
      series: [{ name: "组合", data: portfolio.curve.map((point) => point.cumulative_return) }],
    };
  }, [portfolio]);

  if (assets.length === 0) {
    return <section className="panel analysis-panel">当前没有可用于分析的资产</section>;
  }

  return (
    <section className="panel analysis-panel">
      <div className="panel-header">
        <div className="asset-name">投资研究分析</div>
        <span className="asset-meta">股票使用前复权价格，基金使用单位净值</span>
      </div>

      <div className="analysis-controls">
        <label>
          资产
          <select value={assetId} onChange={(event) => setAssetId(event.target.value)}>
            {assets.map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.name} ({asset.symbol})
              </option>
            ))}
          </select>
        </label>
        <label>
          基准
          <select value={benchmarkId} onChange={(event) => setBenchmarkId(event.target.value)}>
            {assets.map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.name} ({asset.symbol})
              </option>
            ))}
          </select>
        </label>
        <button className="asset-button" onClick={runCompare} disabled={compareLoading}>
          {compareLoading ? "比较中…" : "比较基准"}
        </button>
      </div>

      {metricsLoading ? (
        <div className="status">指标加载中…</div>
      ) : metricsError ? (
        <div className="status">{metricsError}</div>
      ) : metrics ? (
        <div className="summary">
          <span>区间收益 {formatPercent(metrics.cumulative_return)}</span>
          <span>年化收益 {formatPercent(metrics.annualized_return)}</span>
          <span>最大回撤 {formatPercent(metrics.max_drawdown?.drawdown)}</span>
          <span>年化波动 {formatPercent(metrics.annualized_volatility)}</span>
          <span>有效观测 {metrics.count}</span>
          <span>来源 {metrics.source}</span>
          <span>区间 {metrics.first_date ?? "-"} 至 {metrics.last_date ?? "-"}</span>
        </div>
      ) : null}

      {compareError ? <div className="status">{compareError}</div> : null}
      {compareChart ? (
        <LineSeriesChart dates={compareChart.dates} series={compareChart.series} />
      ) : null}
      {compare && compare.error ? <div className="status">{compare.error}</div> : null}
      {compare && compare.count >= 2 ? (
        <div className="summary">
          <span>超额收益 {formatPercent(compare.excess_return)}</span>
          <span>资产累计 {formatPercent(compare.asset_cumulative_return)}</span>
          <span>基准累计 {formatPercent(compare.benchmark_cumulative_return)}</span>
          <span>资产来源 {compare.asset_source}</span>
          <span>基准来源 {compare.benchmark_source}</span>
        </div>
      ) : null}

      <div className="analysis-controls portfolio-controls">
        {assets.map((asset) => (
          <label key={asset.id}>
            {asset.name} ({asset.symbol})
            <input
              type="number"
              min="0"
              placeholder="0"
              value={weights[asset.id] ?? ""}
              onChange={(event) =>
                setWeights((current) => ({ ...current, [asset.id]: event.target.value }))
              }
            />
            %
          </label>
        ))}
        <button className="asset-button" onClick={runPortfolio} disabled={portfolioLoading}>
          {portfolioLoading ? "计算中…" : "分析组合"}
        </button>
      </div>

      {portfolioError ? <div className="status">{portfolioError}</div> : null}
      {portfolio && !portfolio.error ? (
        <div className="summary">
          <span>组合收益 {formatPercent(portfolio.cumulative_return)}</span>
          <span>最大回撤 {formatPercent(portfolio.max_drawdown?.drawdown)}</span>
          <span>年化波动 {formatPercent(portfolio.annualized_volatility)}</span>
          {portfolio.contributions.map((contribution) => {
            const asset = assets.find((item) => item.id === contribution.asset_id);
            return (
              <span key={contribution.asset_id}>
                {asset?.name ?? contribution.asset_id} 贡献 {formatPercent(contribution.contribution)}
              </span>
            );
          })}
        </div>
      ) : null}
      {portfolioChart ? (
        <LineSeriesChart dates={portfolioChart.dates} series={portfolioChart.series} />
      ) : null}
    </section>
  );
}

function LineSeriesChart({
  dates,
  series,
}: {
  dates: string[];
  series: Array<{ name: string; data: Array<number | null> }>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    chartRef.current?.dispose();
    const chart = echarts.init(container);
    chartRef.current = chart;
    chart.setOption({
      backgroundColor: "transparent",
      legend: { data: series.map((item) => item.name), top: 0, textStyle: { color: "#98a2b3" } },
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 16, top: 40, bottom: 24 },
      xAxis: { type: "category", data: dates, boundaryGap: false },
      yAxis: { type: "value", scale: true },
      series: series.map((item) => ({
        name: item.name,
        type: "line",
        data: item.data,
        connectNulls: false,
        showSymbol: false,
      })),
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [dates, series]);

  return <div ref={containerRef} className="analysis-chart" />;
}
