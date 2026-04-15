/**
 * Zod runtime validation schemas for Results Explorer API responses (M27).
 *
 * Purpose:
 *   Validate the RunChartsPayload response at runtime, catching backend
 *   contract violations before they propagate into UI components.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Replace TypeScript static types (use results.ts for that).
 *
 * Dependencies:
 *   - zod v4.
 *
 * Example:
 *   const payload = RunChartsPayloadSchema.parse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Sub-schemas
// ---------------------------------------------------------------------------

export const EquityPointSchema = z.object({
  timestamp: z.string(),
  equity: z.number(),
  drawdown: z.number(),
});

export const FoldBoundarySchema = z.object({
  fold_index: z.number().int(),
  start_timestamp: z.string(),
  end_timestamp: z.string(),
  label: z.string(),
});

export const RegimeSegmentSchema = z.object({
  label: z.string(),
  start_timestamp: z.string(),
  end_timestamp: z.string(),
  color: z.string(),
});

export const TradeRecordSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  side: z.enum(["buy", "sell"]),
  quantity: z.number(),
  entry_price: z.number(),
  exit_price: z.number().nullable(),
  pnl: z.number(),
  fold_index: z.number().int().nullable(),
  regime: z.string().nullable(),
  entry_timestamp: z.string(),
  exit_timestamp: z.string().nullable(),
});

export const SegmentPerformanceSchema = z.object({
  label: z.string(),
  return_pct: z.number(),
  max_drawdown_pct: z.number(),
  sharpe_ratio: z.number(),
  trade_count: z.number().int(),
});

export const TrialSummarySchema = z.object({
  trial_id: z.string(),
  trial_index: z.number().int(),
  parameters: z.record(z.string(), z.unknown()),
  objective_value: z.number(),
  sharpe_ratio: z.number(),
  max_drawdown_pct: z.number(),
  total_return_pct: z.number(),
  trade_count: z.number().int(),
  status: z.string(),
});

export const CandidateMetricsSchema = z.object({
  candidate_id: z.string(),
  label: z.string(),
  objective_value: z.number(),
  sharpe_ratio: z.number(),
  max_drawdown_pct: z.number(),
  total_return_pct: z.number(),
  win_rate: z.number(),
  profit_factor: z.number(),
  trade_count: z.number().int(),
});

// ---------------------------------------------------------------------------
// Main payload schema
// ---------------------------------------------------------------------------

export const RunChartsPayloadSchema = z.object({
  run_id: z.string(),

  // Equity & drawdown
  equity_curve: z.array(EquityPointSchema),
  sampling_applied: z.boolean(),
  raw_equity_point_count: z.number().int(),

  // Fold boundaries
  fold_boundaries: z.array(FoldBoundarySchema),

  // Regime segments
  regime_segments: z.array(RegimeSegmentSchema),

  // Trades
  trades: z.array(TradeRecordSchema),
  trades_truncated: z.boolean(),
  total_trade_count: z.number().int(),

  // Performance breakdown
  fold_performance: z.array(SegmentPerformanceSchema),
  regime_performance: z.array(SegmentPerformanceSchema),

  // Trial summary
  trial_summaries: z.array(TrialSummarySchema),

  // Candidate comparison
  candidate_metrics: z.array(CandidateMetricsSchema),

  // Export
  export_schema_version: z.string(),
});
