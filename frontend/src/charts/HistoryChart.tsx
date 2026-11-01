import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, CandlestickChart, LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { History } from "../types";
import { adaptHistory } from "./adapt";
import { dateToIndex, visibleDates, zoomPercentFor, type ZoomWindow } from "./sync";

echarts.use([BarChart, CandlestickChart, LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer]);

interface HistoryChartProps {
  history: History;
  cursorDate?: string | null;
  onCursorChange?: (date: string | null) => void;
  zoomRange?: ZoomWindow | null;
  onZoomChange?: (range: ZoomWindow | null) => void;
}

export default function HistoryChart({
  history,
  cursorDate = null,
  onCursorChange,
  zoomRange = null,
  onZoomChange,
}: HistoryChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const applyingZoom = useRef(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const spec = adaptHistory(history);
    if (!spec) {
      container.innerHTML = "";
      chartRef.current?.dispose();
      chartRef.current = null;
      return;
    }

    chartRef.current?.dispose();
    const chart = echarts.init(container);
    chartRef.current = chart;
    chart.setOption(buildOption(spec));

    const handleZoom = () => {
      if (applyingZoom.current) return;
      const zoom = chart.getOption().dataZoom as Array<{ start?: number; end?: number }> | undefined;
      const first = Array.isArray(zoom) ? zoom[0] : zoom;
      if (!first || first.start === undefined || first.end === undefined) return;
      onZoomChange?.(visibleDates(spec.dates, first.start, first.end));
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

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.off("datazoom", handleZoom);
      chart.off("updateAxisPointer", handleAxisPointer);
      chart.off("globalout", handleGlobalOut);
      chart.dispose();
      chartRef.current = null;
    };
  }, [history, onCursorChange, onZoomChange]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const spec = adaptHistory(history);
    if (!spec) return;
    const index = dateToIndex(spec.dates, cursorDate);
    if (index >= 0) {
      chart.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: index });
    } else {
      chart.dispatchAction({ type: "hideTip" });
    }
  }, [cursorDate, history]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const spec = adaptHistory(history);
    if (!spec || zoomRange === null) return;
    const percent = zoomPercentFor(spec.dates, zoomRange);
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
  }, [zoomRange, history]);

  return <div ref={containerRef} className="chart" />;
}

function buildOption(spec: ReturnType<typeof adaptHistory>) {
  if (!spec) return {};
  const base = {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" as const },
    textStyle: { color: "#98a2b3" },
  };

  if (spec.kind === "line") {
    return {
      ...base,
      grid: { left: 48, right: 16, top: 24, bottom: 56 },
      xAxis: { type: "category" as const, data: spec.dates, boundaryGap: false },
      yAxis: { type: "value" as const, scale: true },
      dataZoom: [{ type: "inside" as const }, { type: "slider" as const, bottom: 6, height: 16 }],
      series: [
        {
          name: spec.valueName,
          type: "line" as const,
          data: spec.values,
          connectNulls: false,
          showSymbol: false,
          lineStyle: { color: "#6da7ff", width: 2 },
        },
      ],
    };
  }

  return {
    ...base,
    grid: [
      { left: 48, right: 16, top: 16, bottom: "28%" },
      { left: 48, right: 16, top: "72%", bottom: "12%" },
    ],
    xAxis: [
      { type: "category" as const, data: spec.dates, gridIndex: 0, axisLabel: { show: false } },
      { type: "category" as const, data: spec.dates, gridIndex: 1 },
    ],
    yAxis: [
      { type: "value" as const, scale: true, gridIndex: 0 },
      { type: "value" as const, scale: true, gridIndex: 1, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: "inside" as const, xAxisIndex: [0, 1] },
      { type: "slider" as const, xAxisIndex: [0, 1], bottom: 4, height: 16 },
    ],
    series: [
      {
        name: "K线",
        type: "candlestick" as const,
        data: spec.candles,
        itemStyle: { color: "#e05c5c", color0: "#4aa36b", borderColor: "#e05c5c", borderColor0: "#4aa36b" },
      },
      {
        name: "成交量",
        type: "bar" as const,
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: spec.volumes,
        itemStyle: { color: "#53657d" },
      },
    ],
  };
}
