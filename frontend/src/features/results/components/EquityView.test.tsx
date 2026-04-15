/**
 * Tests for EquityView composite container.
 *
 * Verifies that EquityView composes EquityCurve, DrawdownCurve,
 * and overlay components correctly.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityView } from "./EquityView";
import type { RunChartsPayload } from "@/types/results";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeMinimalPayload(): RunChartsPayload {
  return {
    run_id: "01HRUN0000000000000000001",
    equity_curve: Array.from({ length: 100 }, (_, i) => ({
      timestamp: new Date(2026, 0, 1 + i).toISOString(),
      equity: 10000 + i * 10,
      drawdown: -(i % 5),
    })),
    sampling_applied: false,
    raw_equity_point_count: 100,
    fold_boundaries: [],
    regime_segments: [],
    trades: [],
    trades_truncated: false,
    total_trade_count: 0,
    fold_performance: [],
    regime_performance: [],
    trial_summaries: [],
    candidate_metrics: [],
    export_schema_version: "1.0.0",
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EquityView", () => {
  it("renders the equity view container", () => {
    render(<EquityView data={makeMinimalPayload()} engine="recharts" />);
    expect(screen.getByTestId("equity-view")).toBeInTheDocument();
  });

  it("renders the equity curve chart", () => {
    render(<EquityView data={makeMinimalPayload()} engine="recharts" />);
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
  });

  it("renders the drawdown curve chart", () => {
    render(<EquityView data={makeMinimalPayload()} engine="recharts" />);
    expect(screen.getByTestId("drawdown-curve-chart")).toBeInTheDocument();
  });

  it("passes fold boundaries to equity curve when present", () => {
    const payload = makeMinimalPayload();
    payload.fold_boundaries = [
      {
        fold_index: 0,
        start_timestamp: "2026-01-01T00:00:00Z",
        end_timestamp: "2026-02-01T00:00:00Z",
        label: "Fold 1",
      },
    ];
    render(<EquityView data={payload} engine="recharts" />);
    expect(screen.getByTestId("fold-boundary-0")).toBeInTheDocument();
  });
});
