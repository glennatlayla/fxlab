/**
 * Paper trading domain types.
 *
 * Purpose:
 *   Define TypeScript types for paper trading API responses and UI state,
 *   matching the backend contracts for paper execution registration.
 *
 * Responsibilities:
 *   - Define immutable, frozen Pydantic-compatible type shapes.
 *   - Support serialization and deserialization from JSON.
 *   - Document all fields and error conditions.
 *
 * Does NOT:
 *   - Contain validation logic (Zod schemas define this).
 *   - Contain business logic.
 *
 * Dependencies:
 *   - None (pure TypeScript).
 *
 * Error conditions:
 *   - None; this is a pure type definition module.
 *
 * Example:
 *   const config: PaperTradingConfig = {
 *     deployment_id: "01HDEPLOY...",
 *     initial_equity: 10000,
 *     max_position_size: 5000,
 *     max_daily_loss: 1000,
 *     max_leverage: 2,
 *     symbols: ["AAPL", "MSFT"],
 *   };
 */

/**
 * Request payload for registering a deployment for paper trading.
 *
 * All numeric fields are passed as decimal strings to the backend for
 * precision preservation.
 */
export interface PaperTradingRegisterRequest {
  /** Starting hypothetical equity for the paper trading account. */
  initial_equity: string;
  /** Optional initial market prices for symbols: {symbol: price_string}. */
  market_prices?: Record<string, string>;
  /** Fixed commission per order (optional). */
  commission_per_order?: string;
}

/**
 * Response from successful paper trading registration.
 */
export interface PaperTradingRegisterResponse {
  /** ULID of the registered deployment. */
  deployment_id: string;
  /** Status confirmation. */
  status: "registered";
}

/**
 * Paper trading configuration submitted by the form.
 *
 * Combines deployment selection with risk limits and initial equity.
 */
export interface PaperTradingConfig {
  /** ULID of the deployment to paper trade. */
  deployment_id: string;
  /** ULID of the strategy build within the deployment. */
  strategy_build_id: string;
  /** Initial equity in dollars (numeric). */
  initial_equity: number;
  /** Maximum position size in dollars. */
  max_position_size: number;
  /** Maximum daily loss in dollars. */
  max_daily_loss: number;
  /** Maximum leverage multiplier (1–10x). */
  max_leverage: number;
  /** List of symbols to trade. */
  symbols: string[];
}

/**
 * Summary of paper trading configuration for review before submission.
 *
 * Includes human-readable deployment and strategy names, plus all
 * configuration values formatted for display.
 */
export interface PaperTradingReviewSummary {
  /** Deployment name/label. */
  deploymentName: string;
  /** Strategy name/label. */
  strategyName: string;
  /** Initial equity formatted as currency. */
  initialEquityDisplay: string;
  /** Initial equity as number. */
  initialEquity: number;
  /** Max position size formatted as currency. */
  maxPositionSizeDisplay: string;
  /** Max position size as number. */
  maxPositionSize: number;
  /** Max daily loss formatted as currency. */
  maxDailyLossDisplay: string;
  /** Max daily loss as number. */
  maxDailyLoss: number;
  /** Max leverage as string (e.g., "2.5x"). */
  maxLeverageDisplay: string;
  /** Max leverage as number. */
  maxLeverage: number;
  /** Comma-separated symbol list. */
  symbolsDisplay: string;
  /** Symbol list as array. */
  symbols: string[];
}

/**
 * Deployment metadata returned by the API for picker selection.
 */
export interface DeploymentMetadata {
  /** ULID of the deployment. */
  id: string;
  /** Human-readable deployment name. */
  name: string;
  /** Current status (e.g., "active", "paused"). */
  status: "active" | "paused" | "stopped";
}

/**
 * Strategy build metadata returned by the API for picker selection.
 */
export interface StrategyBuildMetadata {
  /** ULID of the strategy build. */
  id: string;
  /** Human-readable strategy name. */
  name: string;
  /** Version or label (optional). */
  version?: string;
}

// ---------------------------------------------------------------------------
// Paper Trading Monitor Types (FE-14)
// ---------------------------------------------------------------------------

/** Paper deployment lifecycle status. */
export type PaperDeploymentStatus =
  | "active"
  | "paused"
  | "frozen"
  | "stopped";

/**
 * Named constants for paper deployment status values.
 *
 * Use these instead of string literals to ensure single-source-of-truth
 * for status comparisons across components and services.
 */
export const PAPER_DEPLOYMENT_STATUS = {
  ACTIVE: "active" as const,
  PAUSED: "paused" as const,
  FROZEN: "frozen" as const,
  STOPPED: "stopped" as const,
} satisfies Record<string, PaperDeploymentStatus>;

/** Order side — direction of the trade. */
export type OrderSide = "long" | "short";

/** Order type — execution method. */
export type OrderType = "market" | "limit" | "stop";

/** Order status — lifecycle. */
export type OrderStatus = "pending" | "filled" | "cancelled";

/**
 * Named constants for order status values.
 */
export const ORDER_STATUS = {
  PENDING: "pending" as const,
  FILLED: "filled" as const,
  CANCELLED: "cancelled" as const,
} satisfies Record<string, OrderStatus>;

/**
 * Summary of a paper trading deployment.
 *
 * Represents a live paper trading simulation with current P&L, equity,
 * and position/order counts. Used in list views and on monitoring cards.
 */
export interface PaperDeploymentSummary {
  /** UUID or ULID identifying the deployment. */
  id: string;
  /** Human-readable strategy name. */
  strategy_name: string;
  /** Current lifecycle status. */
  status: PaperDeploymentStatus;
  /** Current total equity (account balance + unrealized P&L). */
  equity: number;
  /** Starting equity when the deployment began. */
  initial_equity: number;
  /** Unrealized P&L across all open positions (includes fees). */
  unrealized_pnl: number;
  /** Realized P&L from closed positions. */
  realized_pnl: number;
  /** Total P&L (realized + unrealized). */
  total_pnl: number;
  /** Number of currently open positions. */
  open_positions: number;
  /** Number of pending orders. */
  open_orders: number;
  /** ISO-8601 timestamp when deployment started. */
  started_at: string;
  /** ISO-8601 timestamp of the most recent trade (null if no trades yet). */
  last_trade_at?: string | null;
}

/**
 * Single open position in a paper trading deployment.
 *
 * Represents a currently-held stock or future position with current
 * mark-to-market valuation.
 */
export interface PaperPosition {
  /** Trading symbol (e.g., "AAPL", "SPY"). */
  symbol: string;
  /** Position direction: long or short. */
  side: OrderSide;
  /** Number of shares/contracts held. */
  quantity: number;
  /** Entry price per share/contract. */
  entry_price: number;
  /** Current market price per share/contract. */
  current_price: number;
  /** Unrealized P&L for this position (includes fees). */
  unrealized_pnl: number;
  /** Unrealized P&L as a percentage (e.g., 5.23 for +5.23%). */
  pnl_pct: number;
}

/**
 * A single order (pending or completed) in a paper trading deployment.
 *
 * Represents a request to buy/sell a quantity at a specified price/type.
 */
export interface PaperOrder {
  /** Unique order identifier. */
  id: string;
  /** Trading symbol (e.g., "AAPL", "SPY"). */
  symbol: string;
  /** Order direction: buy or sell. */
  side: OrderSide;
  /** Order execution type. */
  type: OrderType;
  /** Order quantity (shares/contracts). */
  quantity: number;
  /** Limit or stop price (null for market orders). */
  price?: number | null;
  /** Current order status. */
  status: OrderStatus;
  /** ISO-8601 timestamp when the order was created. */
  created_at: string;
}
