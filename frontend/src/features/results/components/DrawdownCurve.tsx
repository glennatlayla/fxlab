/**
 * DrawdownCurve — drawdown percentage chart.
 *
 * Purpose:
 *   Renders the portfolio drawdown curve (peak-to-trough percentage)
 *   using the drawdown field from equity data points. Uses either
 *   Recharts or ECharts based on the engine prop.
 *
 * Responsibilities:
 *   - Render drawdown data as an area chart.
 *   - Switch rendering engine based on the engine prop.
 *   - Show empty state when no data points exist.
 *
 * Does NOT:
 *   - Calculate drawdown values (backend provides them).
 *   - Handle equity or overlay rendering.
 *
 * Dependencies:
 *   - DrawdownCurveProps from ../types.
 *   - recharts (AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer).
 *   - echarts-for-react (ReactECharts).
 */

import { memo, useMemo } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import ReactECharts from "echarts-for-react";
import type { DrawdownCurveProps } from "../types";
import { DRAWDOWN_CHART_HEIGHT, COLOR_DRAWDOWN_STROKE, COLOR_DRAWDOWN_FILL } from "../constants";

/**
 * Render the drawdown curve chart.
 *
 * Args:
 *   data: Array of EquityPoint objects (drawdown field used).
 *   engine: "recharts" or "echarts" rendering engine.
 *
 * Returns:
 *   Chart element or empty state.
 */
export const DrawdownCurve = memo(function DrawdownCurve({ data, engine }: DrawdownCurveProps) {
  // Memoize ECharts option to prevent unnecessary re-renders on parent changes.
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
        axisLabel: { formatter: (v: number) => `${v.toFixed(1)}%` },
      },
      series: [
        {
          type: "line" as const,
          data: data.map((p) => p.drawdown),
          showSymbol: false,
          areaStyle: { color: COLOR_DRAWDOWN_FILL },
          lineStyle: { width: 1.5, color: COLOR_DRAWDOWN_STROKE },
        },
      ],
      animation: false,
    }),
    [data],
  );

  if (data.length === 0) {
    return (
      <div
        data-testid="drawdown-curve-empty"
        className="flex h-48 items-center justify-center text-sm text-slate-400"
      >
        No drawdown data available.
      </div>
    );
  }

  return (
    <div
      data-testid="drawdown-curve-chart"
      data-engine={engine}
      role="img"
      aria-label={`Drawdown curve chart with ${data.length} data points`}
      className="w-full"
    >
      {engine === "recharts" ? (
        <ResponsiveContainer width="100%" height={DRAWDOWN_CHART_HEIGHT}>
          <AreaChart data={data}>
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
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
            <Tooltip
              labelFormatter={(ts: string) => new Date(ts).toLocaleString()}
              formatter={(value: number) => [`${value.toFixed(2)}%`, "Drawdown"]}
            />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke={COLOR_DRAWDOWN_STROKE}
              fill={COLOR_DRAWDOWN_FILL}
              strokeWidth={1.5}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <ReactECharts
          style={{ height: DRAWDOWN_CHART_HEIGHT, width: "100%" }}
          option={echartsOption}
        />
      )}
    </div>
  );
});
