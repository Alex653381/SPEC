import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { Asset, History } from "../types";
import { aggregateHistory, type ChartPeriod } from "./aggregate";
import ChartLightbox from "./ChartLightbox";
import { normalizeSeries, type DateRange } from "./normalize";
import { dateToIndex, visibleDates, zoomPercentFor, type ZoomWindow } from "./sync";

echarts.use([LineChart, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

interface NormalizedComparisonChartProps {
  inputs: Array<{ asset: Asset; history: History }>;
  range: DateRange;
  period: ChartPeriod;
  cursorDate?: string | null;
  onCursorChange?: (date: string | null) => void;
  zoomRange?: ZoomWindow | null;
  onZoomChange?: (range: ZoomWindow | null) => void;
}

export default function NormalizedComparisonChart({
  inputs,
  range,
  period,
  cursorDate = null,
  onCursorChange,
  zoomRange = null,
  onZoomChange,
}: NormalizedComparisonChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const applyingZoom = useRef(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const series = inputs.map(({ asset, history }) => normalizeSeries(asset, aggregateHistory(history, period), range));
    const valid = series.filter((item) => item.error === null && item.points.length > 0);
    const invalid = series.filter((item) => item.error !== null || item.points.length === 0);

    if (valid.length === 0) {
      container.innerHTML = "";
      chartRef.current?.dispose();
      chartRef.current = null;
      return;
    }

    const allDates = Array.from(new Set(valid.flatMap((item) => item.points.map((point) => point.date)))).sort();
    const dateIndex = valid.map((item) => new Map(item.points.map((point) => [point.date, point])));

    const chart = echarts.init(container);
    chartRef.current = chart;
    chart.setOption({
      backgroundColor: "transparent",
      legend: { data: valid.map((item) => item.label), top: 0, textStyle: { color: "#98a2b3" } },
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params];
          const first = list[0] as { axisValue?: string } | undefined;
          const head = first?.axisValue ?? "";
          const lines = list.map((entry) => {
            const item = entry as {
              marker?: string;
              seriesName?: string;
              data?: { value?: number | null; raw?: number | null; base?: string | null };
            };
            return `${item.marker ?? ""}${item.seriesName ?? ""}: 指数 ${item.data?.value ?? "-"} · 原值 ${item.data?.raw ?? "-"} · 基准 ${item.data?.base ?? "-"}`;
          });
          return [head, ...lines].join("<br/>");
        },
      },
      grid: { left: 48, right: 16, top: 48, bottom: 64 },
      xAxis: { type: "category", data: allDates, boundaryGap: false },
      yAxis: { type: "value", scale: true, name: "指数" },
      dataZoom: [{ type: "inside" }, { type: "slider", bottom: 6, height: 18 }],
      series: valid.map((item, index) => ({
        name: item.label,
        type: "line",
        connectNulls: false,
        showSymbol: false,
        data: allDates.map((date) => {
          const point = dateIndex[index].get(date);
          return point ? { value: point.index, raw: point.raw, base: item.baseDate } : null;
        }),
      })),
    });

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);

    const handleZoom = () => {
      if (applyingZoom.current) return;
      const zoom = chart.getOption().dataZoom as Array<{ start?: number; end?: number }> | undefined;
      const first = Array.isArray(zoom) ? zoom[0] : zoom;
      if (!first || first.start === undefined || first.end === undefined) return;
      onZoomChange?.(visibleDates(allDates, first.start, first.end));
    };
    const handleAxisPointer = (params: unknown) => {
      const axesInfo = (params as { axesInfo?: Array<{ axisValue?: unknown }> }).axesInfo;
      const axis = axesInfo?.find((item) => typeof item.axisValue === "string");
      onCursorChange?.(axis ? (axis.axisValue as string) : null);
    };
    const handleGlobalOut = () => onCursorChange?.(null);
    chart.on("datazoom", handleZoom);
    chart.on("updateAxisPointer", handleAxisPointer);
    chart.on("globalout", handleGlobalOut);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.off("datazoom", handleZoom);
      chart.off("updateAxisPointer", handleAxisPointer);
      chart.off("globalout", handleGlobalOut);
      chart.dispose();
      chartRef.current = null;
    };
  }, [inputs, range, period, onCursorChange, onZoomChange]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const series = inputs.map(({ asset, history }) => normalizeSeries(asset, aggregateHistory(history, period), range));
    const valid = series.filter((item) => item.error === null && item.points.length > 0);
    const allDates = Array.from(new Set(valid.flatMap((item) => item.points.map((point) => point.date)))).sort();
    const index = dateToIndex(allDates, cursorDate);
    if (index < 0) {
      chart.dispatchAction({ type: "hideTip" });
      return;
    }
    valid.forEach((_, seriesIndex) => {
      const point = valid[seriesIndex].points.find((item) => item.date === allDates[index]);
      if (point) {
        chart.dispatchAction({ type: "showTip", seriesIndex, dataIndex: index });
      }
    });
  }, [cursorDate, inputs, range, period]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || zoomRange === null) return;
    const series = inputs.map(({ asset, history }) => normalizeSeries(asset, aggregateHistory(history, period), range));
    const valid = series.filter((item) => item.error === null && item.points.length > 0);
    const allDates = Array.from(new Set(valid.flatMap((item) => item.points.map((point) => point.date)))).sort();
    const percent = zoomPercentFor(allDates, zoomRange);
    const currentZoom = chart.getOption().dataZoom as Array<{ start?: number; end?: number }> | undefined;
    const current = Array.isArray(currentZoom) ? currentZoom[0] : currentZoom;
    if (
      current &&
      typeof current.start === "number" &&
      typeof current.end === "number" &&
      Math.abs(current.start - percent.start) < 0.05 &&
      Math.abs(current.end - percent.end) < 0.05
    ) {
      return;
    }
    applyingZoom.current = true;
    chart.dispatchAction({ type: "dataZoom", start: percent.start, end: percent.end });
    applyingZoom.current = false;
  }, [zoomRange, inputs, range, period]);

  const invalidNotes = inputs
    .map(({ asset, history }) => normalizeSeries(asset, aggregateHistory(history, period), range))
    .filter((item) => item.error !== null)
    .map((item) => `${item.label}: ${item.error}`);

  return (
    <section className="panel comparison-panel">
      <ChartLightbox>
        <div ref={containerRef} className="chart comparison-chart" />
      </ChartLightbox>
      {invalidNotes.length ? (
        <div className="status">{invalidNotes.join(" · ")}</div>
      ) : null}
    </section>
  );
}
