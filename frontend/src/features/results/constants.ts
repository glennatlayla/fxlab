/**
 * Results Explorer constants — centralized values for charts, tables, and layout.
 *
 * Purpose:
 *   Single source of truth for all magic numbers, colors, and dimension values
 *   used across the Results Explorer feature. Prevents scattered hardcoded values
 *   and ensures consistent theming.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 *
 * Dependencies:
 *   - None (pure constants).
 */

// ---------------------------------------------------------------------------
// Chart dimensions
// ---------------------------------------------------------------------------

/** Height in pixels for the equity curve chart. */
export const EQUITY_CHART_HEIGHT = 320;

/** Height in pixels for the drawdown chart. */
export const DRAWDOWN_CHART_HEIGHT = 200;

// ---------------------------------------------------------------------------
// Chart colors — aligned with Tailwind palette
// ---------------------------------------------------------------------------

/** Equity line color (blue-500). */
export const COLOR_EQUITY_LINE = "#3b82f6";

/** Drawdown stroke color (red-500). */
export const COLOR_DRAWDOWN_STROKE = "#ef4444";

/** Drawdown fill color (red-200). */
export const COLOR_DRAWDOWN_FILL = "#fecaca";

// ---------------------------------------------------------------------------
// Trade blotter
// ---------------------------------------------------------------------------

/** Row height in pixels for the virtual scroller. */
export const TRADE_BLOTTER_ROW_HEIGHT = 36;

/** Visible viewport height in pixels for the trade blotter. */
export const TRADE_BLOTTER_VIEWPORT_HEIGHT = 400;

/** Number of overscan rows above/below the viewport. */
export const TRADE_BLOTTER_OVERSCAN = 20;

// ---------------------------------------------------------------------------
// Trial summary table
// ---------------------------------------------------------------------------

/** Row height in pixels for the trial summary virtualizer. */
export const TRIAL_TABLE_ROW_HEIGHT = 40;

/** Visible viewport height for the trial summary table. */
export const TRIAL_TABLE_VIEWPORT_HEIGHT = 480;

/** Overscan count for the trial summary virtualizer. */
export const TRIAL_TABLE_OVERSCAN = 10;

// ---------------------------------------------------------------------------
// Grid column templates (CSS grid-template-columns)
// ---------------------------------------------------------------------------

/** TradeBlotter column widths. */
export const TRADE_BLOTTER_COLUMNS = "80px 60px 60px 80px 80px 80px 80px";

/** TrialSummaryTable column widths. */
export const TRIAL_TABLE_COLUMNS = "60px 80px 80px 80px 80px 60px 80px";

/** CandidateComparisonTable column widths. */
export const CANDIDATE_TABLE_COLUMNS = "120px 80px 80px 80px 80px 80px 80px 60px";

// ---------------------------------------------------------------------------
// API & retry
// ---------------------------------------------------------------------------

/** Maximum retry attempts for transient API failures (4 total attempts: 1 initial + 3 retries). */
export const API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff (1s, 2s, 4s). */
export const API_RETRY_BASE_DELAY_MS = 1000;

/** Jitter factor for retry backoff (25% randomisation to prevent thundering herd). */
export const API_JITTER_FACTOR = 0.25;

/** Download request timeout in ms (60 seconds for large zip bundles). */
export const DOWNLOAD_TIMEOUT_MS = 60_000;

/** Delay in ms before revoking blob URL after download click (30s for slow systems). */
export const BLOB_REVOKE_DELAY_MS = 30_000;

/** Expected MIME type for export zip bundles. */
export const EXPORT_BLOB_MIME_TYPE = "application/zip";

// ---------------------------------------------------------------------------
// Candidate comparison table
// ---------------------------------------------------------------------------

/** Row height in pixels for the candidate comparison virtualizer. */
export const CANDIDATE_TABLE_ROW_HEIGHT = 36;

/** Visible viewport height for the candidate comparison table. */
export const CANDIDATE_TABLE_VIEWPORT_HEIGHT = 400;

/** Overscan count for the candidate comparison virtualizer. */
export const CANDIDATE_TABLE_OVERSCAN = 10;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_FETCH_RUN_CHARTS = "results.fetch_run_charts";
export const OP_DOWNLOAD_EXPORT = "results.download_export_bundle";
export const OP_FILTER_TRADES = "results.filter_trades";
export const OP_RENDER_PAGE = "results.render_page";
