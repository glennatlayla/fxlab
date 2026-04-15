/**
 * Tests for SegmentedPerformanceBar component.
 *
 * Verifies per-fold and per-regime performance bar chart rendering.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SegmentedPerformanceBar } from "./SegmentedPerformanceBar";
import type { SegmentPerformance } from "@/types/results";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeFoldPerformance(): SegmentPerformance[] {
  return [
    {
      label: "Fold 1",
      return_pct: 12.5,
      max_drawdown_pct: -8.3,
      sharpe_ratio: 1.2,
      trade_count: 50,
    },
    {
      label: "Fold 2",
      return_pct: 8.1,
      max_drawdown_pct: -5.1,
      sharpe_ratio: 0.9,
      trade_count: 45,
    },
  ];
}

function makeRegimePerformance(): SegmentPerformance[] {
  return [
    { label: "Bull", return_pct: 18.0, max_drawdown_pct: -4.0, sharpe_ratio: 1.8, trade_count: 70 },
    {
      label: "Bear",
      return_pct: -3.5,
      max_drawdown_pct: -15.0,
      sharpe_ratio: -0.2,
      trade_count: 30,
    },
  ];
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SegmentedPerformanceBar", () => {
  it("renders performance bar chart container", () => {
    render(
      <SegmentedPerformanceBar
        foldPerformance={makeFoldPerformance()}
        regimePerformance={makeRegimePerformance()}
      />,
    );
    expect(screen.getByTestId("segmented-performance-bar")).toBeInTheDocument();
  });

  it("renders fold performance segments", () => {
    render(
      <SegmentedPerformanceBar foldPerformance={makeFoldPerformance()} regimePerformance={[]} />,
    );
    expect(screen.getByText("Fold 1")).toBeInTheDocument();
    expect(screen.getByText("Fold 2")).toBeInTheDocument();
  });

  it("renders regime performance segments", () => {
    render(
      <SegmentedPerformanceBar foldPerformance={[]} regimePerformance={makeRegimePerformance()} />,
    );
    expect(screen.getByText("Bull")).toBeInTheDocument();
    expect(screen.getByText("Bear")).toBeInTheDocument();
  });

  it("renders empty state when both arrays are empty", () => {
    render(<SegmentedPerformanceBar foldPerformance={[]} regimePerformance={[]} />);
    expect(screen.getByTestId("segmented-performance-empty")).toBeInTheDocument();
  });
});
