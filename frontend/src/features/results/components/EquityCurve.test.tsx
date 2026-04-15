/**
 * Tests for EquityCurve component.
 *
 * AC-1: Equity curve renders via Recharts for small series (<500 points)
 *        and via ECharts for large series (>=500 points).
 * AC-5: Fold boundaries render as overlay markers on the equity chart
 *        for walk-forward runs.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityCurve } from "./EquityCurve";
import type { EquityPoint, FoldBoundary, RegimeSegment } from "@/types/results";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEquityPoints(count: number): EquityPoint[] {
  return Array.from({ length: count }, (_, i) => ({
    timestamp: new Date(2026, 0, 1 + i).toISOString(),
    equity: 10000 + i * 10,
    drawdown: -(i % 5),
  }));
}

function makeFoldBoundaries(): FoldBoundary[] {
  return [
    {
      fold_index: 0,
      start_timestamp: "2026-01-01T00:00:00Z",
      end_timestamp: "2026-03-01T00:00:00Z",
      label: "Fold 1",
    },
    {
      fold_index: 1,
      start_timestamp: "2026-03-01T00:00:00Z",
      end_timestamp: "2026-06-01T00:00:00Z",
      label: "Fold 2",
    },
  ];
}

function makeRegimeSegments(): RegimeSegment[] {
  return [
    {
      label: "bull",
      start_timestamp: "2026-01-01T00:00:00Z",
      end_timestamp: "2026-02-15T00:00:00Z",
      color: "#22c55e",
    },
  ];
}

// ---------------------------------------------------------------------------
// AC-1: Chart engine selection
// ---------------------------------------------------------------------------

describe("EquityCurve", () => {
  it("renders with recharts engine for a 400-point series", () => {
    const data = makeEquityPoints(400);
    render(<EquityCurve data={data} engine="recharts" />);
    const chart = screen.getByTestId("equity-curve-chart");
    expect(chart).toBeInTheDocument();
    expect(chart).toHaveAttribute("data-engine", "recharts");
  });

  it("renders with echarts engine for a 1500-point series", () => {
    const data = makeEquityPoints(1500);
    render(<EquityCurve data={data} engine="echarts" />);
    const chart = screen.getByTestId("equity-curve-chart");
    expect(chart).toBeInTheDocument();
    expect(chart).toHaveAttribute("data-engine", "echarts");
  });

  it("renders empty state for zero data points", () => {
    render(<EquityCurve data={[]} engine="recharts" />);
    expect(screen.getByTestId("equity-curve-empty")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // AC-5: Fold-boundary overlays
  // ---------------------------------------------------------------------------

  it("renders fold boundary markers when foldBoundaries are provided", () => {
    const data = makeEquityPoints(100);
    const folds = makeFoldBoundaries();
    render(<EquityCurve data={data} engine="recharts" foldBoundaries={folds} />);
    const markers = screen.getAllByTestId(/^fold-boundary-/);
    expect(markers).toHaveLength(2);
  });

  it("does not render fold markers when foldBoundaries is empty", () => {
    const data = makeEquityPoints(100);
    render(<EquityCurve data={data} engine="recharts" foldBoundaries={[]} />);
    expect(screen.queryByTestId(/^fold-boundary-/)).not.toBeInTheDocument();
  });

  it("renders regime segments when regimeSegments are provided", () => {
    const data = makeEquityPoints(100);
    render(<EquityCurve data={data} engine="recharts" regimeSegments={makeRegimeSegments()} />);
    const segments = screen.getAllByTestId(/^regime-segment-/);
    expect(segments).toHaveLength(1);
  });
});
