/**
 * useChartEngine — select the appropriate chart library based on data size.
 *
 * Purpose:
 *   Recharts is suitable for small datasets (< 500 points) with good
 *   React integration. For larger datasets, ECharts provides better
 *   canvas-based rendering performance with built-in downsampling.
 *
 * Args:
 *   dataLength — the number of data points to be rendered.
 *
 * Returns:
 *   "recharts" when dataLength < THRESHOLD, "echarts" otherwise.
 *
 * Example:
 *   const engine = useChartEngine(400);  // "recharts"
 *   const engine = useChartEngine(600);  // "echarts"
 */

import { useMemo } from "react";

/** Crossover point: datasets above this size use ECharts. */
const CHART_ENGINE_THRESHOLD = 500;

export type ChartEngine = "recharts" | "echarts";

export function useChartEngine(dataLength: number): ChartEngine {
  return useMemo(() => {
    return dataLength < CHART_ENGINE_THRESHOLD ? "recharts" : "echarts";
  }, [dataLength]);
}
