/**
 * TypeScript types for the M2.C3 run results sub-resource endpoints.
 *
 * Purpose:
 *   Mirror the wire-format Pydantic models defined in
 *   ``libs/contracts/run_results.py`` so the React UI consumes the
 *   M2.C3 ``GET /runs/{run_id}/results/{equity-curve,blotter,metrics}``
 *   endpoints with full type safety.
 *
 * Responsibilities:
 *   - Define EquityCurvePoint / EquityCurveResponse — equity curve sub-resource shape.
 *   - Define TradeBlotterEntry / TradeBlotterPage — paginated trade blotter shape.
 *   - Define RunMetrics — flattened summary metrics shape.
 *   - Re-export pagination defaults that match the backend contract.
 *
 * Does NOT:
 *   - Contain rendering, formatting, or fetch logic — pure types only.
 *
 * Dependencies:
 *   - none (pure TypeScript types).
 *
 * Wire-format note:
 *   Pydantic ``Decimal`` fields are serialized over JSON as JSON numbers
 *   by FastAPI's default JSON encoder for response models. M2.C3 endpoints
 *   return them as JSON numbers, so we type them as ``number`` here. Should
 *   the backend switch to string-encoded decimals for currency precision,
 *   update these types and the formatting helpers in RunResults.tsx.
 *
 * Example:
 *   const metrics: RunMetrics = await getMetrics("01HRUN…");
 */

// ---------------------------------------------------------------------------
// Pagination contract — mirrors libs/contracts/run_results.py
// ---------------------------------------------------------------------------

/** Default trades-per-page when ``page_size`` is omitted from the request. */
export const DEFAULT_BLOTTER_PAGE_SIZE = 100;

/** Hard ceiling on ``page_size``; requests above this surface as HTTP 422. */
export const MAX_BLOTTER_PAGE_SIZE = 1000;

// ---------------------------------------------------------------------------
// Equity curve
// ---------------------------------------------------------------------------

/**
 * One sample on the equity curve.
 *
 * Attributes:
 *   timestamp: ISO-8601 UTC timestamp string.
 *   equity: Portfolio equity at this point (>= 0).
 */
export interface EquityCurvePoint {
  timestamp: string;
  equity: number;
}

/**
 * Response body for ``GET /runs/{run_id}/results/equity-curve``.
 *
 * Attributes:
 *   run_id: ULID of the run.
 *   point_count: Number of samples in ``points`` (mirrors ``points.length``).
 *   points: Samples ordered ascending by timestamp.
 */
export interface EquityCurveResponse {
  run_id: string;
  point_count: number;
  points: EquityCurvePoint[];
}

// ---------------------------------------------------------------------------
// Trade blotter
// ---------------------------------------------------------------------------

/**
 * A single executed trade row in the blotter.
 *
 * Attributes:
 *   trade_id: Stable identifier (e.g. ``trade-000001``).
 *   timestamp: ISO-8601 UTC execution timestamp.
 *   symbol: Instrument symbol.
 *   side: ``"buy"`` or ``"sell"``.
 *   quantity: Trade size (> 0).
 *   price: Execution price (> 0).
 *   commission: Commission paid (>= 0, default 0).
 *   slippage: Slippage cost (>= 0, default 0).
 */
export interface TradeBlotterEntry {
  trade_id: string;
  timestamp: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  commission: number;
  slippage: number;
}

/**
 * Response body for ``GET /runs/{run_id}/results/blotter``.
 *
 * Pagination contract:
 *   - ``page`` is 1-based.
 *   - ``page_size`` defaults to DEFAULT_BLOTTER_PAGE_SIZE (100), max
 *     MAX_BLOTTER_PAGE_SIZE (1000).
 *   - Trades sorted ascending by ``(timestamp, trade_id)``.
 *   - Out-of-range pages return an empty ``trades`` array but keep
 *     ``total_count`` and ``total_pages`` populated.
 */
export interface TradeBlotterPage {
  run_id: string;
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
  trades: TradeBlotterEntry[];
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

/**
 * Response body for ``GET /runs/{run_id}/results/metrics``.
 *
 * Surfaces the headline performance metrics from the backtest engine.
 * ``summary_metrics`` is engine-specific; the explicit fields cover the
 * common backtest-engine outputs.
 *
 * Attributes:
 *   run_id: ULID of the run.
 *   completed_at: ISO-8601 timestamp when the engine finished, null if not completed.
 *   total_return_pct: Total return percentage.
 *   annualized_return_pct: Annualized return percentage.
 *   max_drawdown_pct: Maximum drawdown (typically negative or zero).
 *   sharpe_ratio: Annualized Sharpe ratio.
 *   total_trades: Number of trades executed.
 *   win_rate: Fraction of winning trades, 0.0-1.0.
 *   profit_factor: Gross profit / gross loss.
 *   final_equity: Ending portfolio equity.
 *   bars_processed: Number of bars evaluated by the engine.
 *   summary_metrics: Engine-specific flattened metrics map.
 */
export interface RunMetrics {
  run_id: string;
  completed_at: string | null;
  total_return_pct: number | null;
  annualized_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  total_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  final_equity: number | null;
  bars_processed: number;
  summary_metrics: Record<string, unknown>;
}
