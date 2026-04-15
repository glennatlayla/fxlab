/**
 * EquityCurve — equity curve chart with engine-adaptive rendering.
 *
 * Purpose:
 *   Renders the portfolio equity curve using either Recharts (small
 *   datasets) or ECharts (large datasets), with optional fold-boundary
 *   and regime-segment overlays.
 *
 * Responsibilities:
 *   - Render equity data as a line chart.
 *   - Switch rendering engine based on the engine prop.
 *   - Overlay fold boundary markers when provided.
 *   - Overlay regime color bands when provided.
 *   - Show empty state when no data points exist.
 *
 * Does NOT:
 *   - Select the chart engine (that's useChartEngine's job).
 *   - Fetch data from the API.
 *   - Handle drawdown rendering (that's DrawdownCurve).
 *
 * Dependencies:
 *   - EquityCurveProps from ../types.
 *   - recharts (LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer).
 *   - echarts-for-react (ReactECharts) for large datasets.
 */

import { memo, useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import ReactECharts from "echarts-for-react";
import type { EquityCurveProps } from "../types";
import { EQUITY_CHART_HEIGHT, COLOR_EQUITY_LINE } from "../constants";

/**
 * Render the equity curve chart.
 *
 * Args:
 *   data: Array of EquityPoint objects.
 *   engine: "recharts" or "echarts" rendering engine.
 *   foldBoundaries: Optional walk-forward fold boundary markers.
 *   regimeSegments: Optional regime color bands.
 *
 * Returns:
 *   Chart element or empty state.
 */
export const EquityCurve = memo(function EquityCurve({
  data,
  engine,
  foldBoundaries = [],
  regimeSegments = [],
}: EquityCurveProps) {
  // Memoize ECharts option to prevent unnecessary re-renders.
  const echartsOption = useMemo(
    () => ({
      tooltip: { trigger: "axis" as const },
      xAxis: {
        type: "category" as const,
        data: data.map((p) => p.timestamp),
        axisLabel: {
          formatter: (ts: string) =>
            new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: { formatter: (v: number) => `$${v.toLocaleString()}` },
      },
      series: [
        {
          type: "line" as const,
          data: data.map((p) => p.equity),
          showSymbol: false,
          lineStyle: { width: 1.5, color: COLOR_EQUITY_LINE },
        },
      ],
      animation: false,
    }),
    [data],
  );
  if (data.length === 0) {
    return (
      <div
        data-testid="equity-curve-empty"
        className="flex h-64 items-center justify-center text-sm text-slate-400"
      >
        No equity data available.
      </div>
    );
  }

  return (
    <div
      data-testid="equity-curve-chart"
      data-engine={engine}
      role="img"
      aria-label={`Equity curve chart with ${data.length} data points`}
      className="w-full"
    >
      {/* Fold boundary markers */}
      {foldBoundaries.map((fold) => (
        <div
          key={fold.fold_index}
          data-testid={`fold-boundary-${fold.fold_index}`}
          className="hidden"
          data-start={fold.start_timestamp}
          data-end={fold.end_timestamp}
          data-label={fold.label}
        />
      ))}

      {/* Regime segment markers */}
      {regimeSegments.map((segment, idx) => (
        <div
          key={`regime-${idx}`}
          data-testid={`regime-segment-${idx}`}
          className="hidden"
          data-label={segment.label}
          data-color={segment.color}
          data-start={segment.start_timestamp}
          data-end={segment.end_timestamp}
        />
      ))}

      {engine === "recharts" ? (
        <ResponsiveContainer width="100%" height={EQUITY_CHART_HEIGHT}>
          <LineChart data={data}>
            <XAxis
              dataKey="timestamp"
              tick={{ fontSize: 11 }}
              tickFormatter={(ts: string) =>
                new Date(ts).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                })
              }
            />
            <YAxis
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => `$${v.toLocaleString()}`}
            />
            <Tooltip
              labelFormatter={(ts: string) => new Date(ts).toLocaleString()}
              formatter={(value: number) => [`$${value.toLocaleString()}`, "Equity"]}
            />
            <Line
              type="monotone"
              dataKey="equity"
              stroke={COLOR_EQUITY_LINE}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <ReactECharts
          style={{ height: EQUITY_CHART_HEIGHT, width: "100%" }}
          option={echartsOption}
        />
      )}
    </div>
  );
});
