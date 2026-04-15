/**
 * Zod schema validation tests for Results Explorer types.
 *
 * Tests runtime validation of the RunChartsPayload and its sub-schemas
 * against valid and invalid inputs.
 */

import { describe, it, expect } from "vitest";
import {
  EquityPointSchema,
  FoldBoundarySchema,
  RegimeSegmentSchema,
  TradeRecordSchema,
  SegmentPerformanceSchema,
  TrialSummarySchema,
  CandidateMetricsSchema,
  RunChartsPayloadSchema,
} from "./results.schemas";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeValidEquityPoint() {
  return { timestamp: "2026-01-01T00:00:00Z", equity: 10000, drawdown: -2.5 };
}

function makeValidFoldBoundary() {
  return {
    fold_index: 0,
    start_timestamp: "2026-01-01T00:00:00Z",
    end_timestamp: "2026-06-01T00:00:00Z",
    label: "Fold 1",
  };
}

function makeValidRegimeSegment() {
  return {
    label: "bull",
    start_timestamp: "2026-01-01T00:00:00Z",
    end_timestamp: "2026-03-01T00:00:00Z",
    color: "#22c55e",
  };
}

function makeValidTradeRecord() {
  return {
    id: "t001",
    symbol: "AAPL",
    side: "buy" as const,
    quantity: 100,
    entry_price: 150.0,
    exit_price: 155.0,
    pnl: 500,
    fold_index: 0,
    regime: "bull",
    entry_timestamp: "2026-01-15T10:00:00Z",
    exit_timestamp: "2026-01-20T14:00:00Z",
  };
}

function makeValidTrialSummary() {
  return {
    trial_id: "01HTRIAL000000000000000001",
    trial_index: 0,
    parameters: { lookback: 20, threshold: 0.5 },
    objective_value: 1.85,
    sharpe_ratio: 1.85,
    max_drawdown_pct: -12.3,
    total_return_pct: 45.2,
    trade_count: 120,
    status: "completed",
  };
}

function makeValidCandidateMetrics() {
  return {
    candidate_id: "01HCAND000000000000000001",
    label: "Best Trial",
    objective_value: 1.85,
    sharpe_ratio: 1.85,
    max_drawdown_pct: -12.3,
    total_return_pct: 45.2,
    win_rate: 0.58,
    profit_factor: 1.7,
    trade_count: 120,
  };
}

function makeValidRunChartsPayload() {
  return {
    run_id: "01HRUN0000000000000000001",
    equity_curve: [makeValidEquityPoint()],
    sampling_applied: false,
    raw_equity_point_count: 1,
    fold_boundaries: [],
    regime_segments: [],
    trades: [makeValidTradeRecord()],
    trades_truncated: false,
    total_trade_count: 1,
    fold_performance: [],
    regime_performance: [],
    trial_summaries: [makeValidTrialSummary()],
    candidate_metrics: [],
    export_schema_version: "1.0.0",
  };
}

// ---------------------------------------------------------------------------
// EquityPoint
// ---------------------------------------------------------------------------

describe("EquityPointSchema", () => {
  it("accepts a valid equity point", () => {
    const result = EquityPointSchema.safeParse(makeValidEquityPoint());
    expect(result.success).toBe(true);
  });

  it("rejects missing equity field", () => {
    const result = EquityPointSchema.safeParse({
      timestamp: "2026-01-01T00:00:00Z",
      drawdown: -2.5,
    });
    expect(result.success).toBe(false);
  });

  it("rejects non-numeric equity", () => {
    const result = EquityPointSchema.safeParse({
      ...makeValidEquityPoint(),
      equity: "not-a-number",
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// FoldBoundary
// ---------------------------------------------------------------------------

describe("FoldBoundarySchema", () => {
  it("accepts a valid fold boundary", () => {
    const result = FoldBoundarySchema.safeParse(makeValidFoldBoundary());
    expect(result.success).toBe(true);
  });

  it("rejects missing label", () => {
    const { label: _, ...partial } = makeValidFoldBoundary();
    const result = FoldBoundarySchema.safeParse(partial);
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// RegimeSegment
// ---------------------------------------------------------------------------

describe("RegimeSegmentSchema", () => {
  it("accepts a valid regime segment", () => {
    const result = RegimeSegmentSchema.safeParse(makeValidRegimeSegment());
    expect(result.success).toBe(true);
  });

  it("rejects missing color", () => {
    const { color: _, ...partial } = makeValidRegimeSegment();
    const result = RegimeSegmentSchema.safeParse(partial);
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// TradeRecord
// ---------------------------------------------------------------------------

describe("TradeRecordSchema", () => {
  it("accepts a valid trade record", () => {
    const result = TradeRecordSchema.safeParse(makeValidTradeRecord());
    expect(result.success).toBe(true);
  });

  it("accepts null exit_price (open position)", () => {
    const result = TradeRecordSchema.safeParse({
      ...makeValidTradeRecord(),
      exit_price: null,
      exit_timestamp: null,
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid side value", () => {
    const result = TradeRecordSchema.safeParse({
      ...makeValidTradeRecord(),
      side: "short",
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// SegmentPerformance
// ---------------------------------------------------------------------------

describe("SegmentPerformanceSchema", () => {
  it("accepts valid segment performance", () => {
    const result = SegmentPerformanceSchema.safeParse({
      label: "Fold 1",
      return_pct: 12.5,
      max_drawdown_pct: -8.3,
      sharpe_ratio: 1.2,
      trade_count: 50,
    });
    expect(result.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// TrialSummary
// ---------------------------------------------------------------------------

describe("TrialSummarySchema", () => {
  it("accepts a valid trial summary", () => {
    const result = TrialSummarySchema.safeParse(makeValidTrialSummary());
    expect(result.success).toBe(true);
  });

  it("rejects missing objective_value", () => {
    const { objective_value: _, ...partial } = makeValidTrialSummary();
    const result = TrialSummarySchema.safeParse(partial);
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// CandidateMetrics
// ---------------------------------------------------------------------------

describe("CandidateMetricsSchema", () => {
  it("accepts valid candidate metrics", () => {
    const result = CandidateMetricsSchema.safeParse(makeValidCandidateMetrics());
    expect(result.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// RunChartsPayload (main response)
// ---------------------------------------------------------------------------

describe("RunChartsPayloadSchema", () => {
  it("accepts a valid full payload", () => {
    const result = RunChartsPayloadSchema.safeParse(makeValidRunChartsPayload());
    expect(result.success).toBe(true);
  });

  it("accepts payload with sampling_applied true", () => {
    const payload = {
      ...makeValidRunChartsPayload(),
      sampling_applied: true,
      raw_equity_point_count: 5000,
    };
    const result = RunChartsPayloadSchema.safeParse(payload);
    expect(result.success).toBe(true);
  });

  it("accepts payload with trades_truncated true", () => {
    const payload = {
      ...makeValidRunChartsPayload(),
      trades_truncated: true,
      total_trade_count: 8000,
    };
    const result = RunChartsPayloadSchema.safeParse(payload);
    expect(result.success).toBe(true);
  });

  it("rejects missing run_id", () => {
    const { run_id: _, ...partial } = makeValidRunChartsPayload();
    const result = RunChartsPayloadSchema.safeParse(partial);
    expect(result.success).toBe(false);
  });

  it("rejects non-boolean sampling_applied", () => {
    const payload = {
      ...makeValidRunChartsPayload(),
      sampling_applied: "yes",
    };
    const result = RunChartsPayloadSchema.safeParse(payload);
    expect(result.success).toBe(false);
  });

  it("accepts empty arrays for optional collections", () => {
    const result = RunChartsPayloadSchema.safeParse(makeValidRunChartsPayload());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.fold_boundaries).toHaveLength(0);
      expect(result.data.regime_segments).toHaveLength(0);
      expect(result.data.candidate_metrics).toHaveLength(0);
    }
  });
});
