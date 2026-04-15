/**
 * Tests for DrawdownCurve component.
 *
 * Verifies the drawdown chart renders correctly using the drawdown
 * field from equity data points.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DrawdownCurve } from "./DrawdownCurve";
import type { EquityPoint } from "@/types/results";

function makeEquityPoints(count: number): EquityPoint[] {
  return Array.from({ length: count }, (_, i) => ({
    timestamp: new Date(2026, 0, 1 + i).toISOString(),
    equity: 10000 + i * 10,
    drawdown: -(i % 10),
  }));
}

describe("DrawdownCurve", () => {
  it("renders drawdown chart with correct engine attribute", () => {
    render(<DrawdownCurve data={makeEquityPoints(100)} engine="recharts" />);
    const chart = screen.getByTestId("drawdown-curve-chart");
    expect(chart).toBeInTheDocument();
    expect(chart).toHaveAttribute("data-engine", "recharts");
  });

  it("renders echarts engine for large dataset", () => {
    render(<DrawdownCurve data={makeEquityPoints(600)} engine="echarts" />);
    const chart = screen.getByTestId("drawdown-curve-chart");
    expect(chart).toHaveAttribute("data-engine", "echarts");
  });

  it("renders empty state for zero data points", () => {
    render(<DrawdownCurve data={[]} engine="recharts" />);
    expect(screen.getByTestId("drawdown-curve-empty")).toBeInTheDocument();
  });
});
