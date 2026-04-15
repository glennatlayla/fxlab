/**
 * Domain types for the Results Explorer feature (M27).
 *
 * Purpose:
 *   TypeScript interfaces mirroring the backend `RunChartsPayload` from
 *   `GET /runs/{run_id}/charts`. Used across the results feature for
 *   type safety in equity curves, drawdowns, trade blotters, and trial
 *   summary tables.
 *
 * Does NOT:
 *   - Contain runtime validation (see results.schemas.ts for Zod).
 *   - Contain business logic or UI rendering.
 *
 * Dependencies:
 *   - None (pure type definitions).
 */

// ---------------------------------------------------------------------------
// Equity curve types
// ---------------------------------------------------------------------------

/** Single point on the equity curve (timestamp + value). */
export interface EquityPoint {
  /** ISO-8601 timestamp or epoch milliseconds. */
  timestamp: string;
  /** Portfolio equity value at this point. */
  equity: number;
  /** Drawdown percentage from peak (0 to -100). */
  drawdown: number;
}

/** Walk-forward fold boundary marker. */
export interface FoldBoundary {
  /** Fold index (0-based). */
  fold_index: number;
  /** ISO-8601 timestamp marking the fold start. */
  start_timestamp: string;
  /** ISO-8601 timestamp marking the fold end. */
  end_timestamp: string;
  /** Fold label (e.g., "Fold 1", "Fold 2"). */
  label: string;
}

/** Regime color band on the equity chart. */
export interface RegimeSegment {
  /** Regime label (e.g., "bull", "bear", "sideways"). */
  label: string;
  /** ISO-8601 start timestamp. */
  start_timestamp: string;
  /** ISO-8601 end timestamp. */
  end_timestamp: string;
  /** Hex color for this regime band. */
  color: string;
}

// ---------------------------------------------------------------------------
// Trade types
// ---------------------------------------------------------------------------

/** Individual trade record in the trade blotter. */
export interface TradeRecord {
  /** Trade ID. */
  id: string;
  /** Trading symbol (e.g., "AAPL", "ES"). */
  symbol: string;
  /** Trade side: "buy" or "sell". */
  side: "buy" | "sell";
  /** Number of units traded. */
  quantity: number;
  /** Entry price. */
  entry_price: number;
  /** Exit price (null if position still open). */
  exit_price: number | null;
  /** Profit/loss in account currency. */
  pnl: number;
  /** Fold index (for walk-forward runs). */
  fold_index: number | null;
  /** Regime label at trade entry. */
  regime: string | null;
  /** ISO-8601 entry timestamp. */
  entry_timestamp: string;
  /** ISO-8601 exit timestamp (null if still open). */
  exit_timestamp: string | null;
}

// ---------------------------------------------------------------------------
// Performance metrics
// ---------------------------------------------------------------------------

/** Per-segment performance breakdown (fold or regime). */
export interface SegmentPerformance {
  /** Segment label (fold name or regime name). */
  label: string;
  /** Annualised return percentage. */
  return_pct: number;
  /** Maximum drawdown percentage. */
  max_drawdown_pct: number;
  /** Sharpe ratio. */
  sharpe_ratio: number;
  /** Number of trades in this segment. */
  trade_count: number;
}

// ---------------------------------------------------------------------------
// Trial summary
// ---------------------------------------------------------------------------

/** Trial summary row for the trial summary table. */
export interface TrialSummary {
  /** Trial ID (ULID). */
  trial_id: string;
  /** Trial index (0-based). */
  trial_index: number;
  /** Parameter set used for this trial. */
  parameters: Record<string, unknown>;
  /** Objective metric value. */
  objective_value: number;
  /** Sharpe ratio achieved. */
  sharpe_ratio: number;
  /** Maximum drawdown percentage. */
  max_drawdown_pct: number;
  /** Total return percentage. */
  total_return_pct: number;
  /** Number of trades. */
  trade_count: number;
  /** Trial status. */
  status: string;
}

// ---------------------------------------------------------------------------
// Candidate comparison
// ---------------------------------------------------------------------------

/** Candidate row for side-by-side metric comparison. */
export interface CandidateMetrics {
  /** Candidate ID. */
  candidate_id: string;
  /** Display label. */
  label: string;
  /** Objective metric value. */
  objective_value: number;
  /** Sharpe ratio. */
  sharpe_ratio: number;
  /** Maximum drawdown percentage. */
  max_drawdown_pct: number;
  /** Total return percentage. */
  total_return_pct: number;
  /** Win rate (0 to 1). */
  win_rate: number;
  /** Profit factor. */
  profit_factor: number;
  /** Trade count. */
  trade_count: number;
}

// ---------------------------------------------------------------------------
// RunChartsPayload — main API response
// ---------------------------------------------------------------------------

/**
 * Full charts payload returned by GET /runs/{run_id}/charts.
 *
 * Contains all data needed to render the Results Explorer page.
 */
export interface RunChartsPayload {
  /** Run ID this payload belongs to. */
  run_id: string;

  // -- Equity & drawdown --
  /** Equity curve data points (may be LTTB-downsampled). */
  equity_curve: EquityPoint[];
  /** True if server-side LTTB downsampling was applied. */
  sampling_applied: boolean;
  /** Original number of equity points before downsampling. */
  raw_equity_point_count: number;

  // -- Fold boundaries --
  /** Walk-forward fold boundaries (empty if not a walk-forward run). */
  fold_boundaries: FoldBoundary[];

  // -- Regime segments --
  /** Regime color bands (empty if no regime detection). */
  regime_segments: RegimeSegment[];

  // -- Trades --
  /** Trade records (may be truncated to 5,000). */
  trades: TradeRecord[];
  /** True if trades were truncated (total > 5,000). */
  trades_truncated: boolean;
  /** Total trade count before truncation. */
  total_trade_count: number;

  // -- Performance breakdown --
  /** Per-fold performance segments. */
  fold_performance: SegmentPerformance[];
  /** Per-regime performance segments. */
  regime_performance: SegmentPerformance[];

  // -- Trial summary --
  /** Trial summary rows (all trials). */
  trial_summaries: TrialSummary[];

  // -- Candidate comparison --
  /** Candidate metrics for comparison (empty if < 2 candidates). */
  candidate_metrics: CandidateMetrics[];

  // -- Export --
  /** Schema version for the export bundle. */
  export_schema_version: string;
}

// ---------------------------------------------------------------------------
// Trade blotter filter state
// ---------------------------------------------------------------------------

/** Filter state for the TradeBlotter component. */
export interface TradeBlotterFilters {
  symbol: string | null;
  side: "buy" | "sell" | null;
  fold_index: number | null;
  regime: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Threshold above which trades are truncated by the backend. */
export const TRADE_TRUNCATION_LIMIT = 5_000;

/** Default chart engine threshold from useChartEngine. */
export const CHART_ENGINE_THRESHOLD = 500;

/** Number of top-N trials to highlight in the trial summary table. */
export const TOP_N_TRIALS = 5;
