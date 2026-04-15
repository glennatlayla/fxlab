/**
 * Risk settings domain types.
 *
 * Purpose:
 *   Define TypeScript types for risk limit API responses and UI state,
 *   matching the backend contracts in libs.contracts.risk.
 *
 * Responsibilities:
 *   - Define immutable, frozen Pydantic-compatible type shapes.
 *   - Support serialization and deserialization from JSON.
 *   - Document all fields and error conditions.
 *
 * Does NOT:
 *   - Contain validation logic (Pydantic on backend does this).
 *   - Contain business logic.
 *
 * Dependencies:
 *   - None (pure TypeScript).
 *
 * Error conditions:
 *   - None; this is a pure type definition module.
 *
 * Example:
 *   const settings: RiskSettings = {
 *     deployment_id: "01HDEPLOY...",
 *     max_position_size: "10000",
 *     max_daily_loss: "5000",
 *     max_order_value: "50000",
 *     max_concentration_pct: "25",
 *     max_open_orders: 100,
 *   };
 */

/**
 * Current risk settings for a deployment.
 *
 * All numeric limits are returned as strings from the API (decimal precision)
 * and converted to numbers in the UI for arithmetic operations.
 */
export interface RiskSettings {
  deployment_id: string;
  max_position_size: string;
  max_daily_loss: string;
  max_order_value: string;
  max_concentration_pct: string;
  max_open_orders: number;
}

/**
 * Partial update to risk settings.
 *
 * All fields are optional; only specified fields are updated on the server.
 */
export interface RiskSettingsUpdate {
  max_position_size?: string;
  max_daily_loss?: string;
  max_order_value?: string;
  max_concentration_pct?: string;
  max_open_orders?: number;
}

/**
 * Represents a single changed field in a risk settings update.
 *
 * Used to display a diff of current vs. proposed values with change percentage
 * and large-change indicators for user review before applying updates.
 */
export interface RiskSettingsDiff {
  /** Field key (e.g., "max_position_size"). */
  field: string;
  /** Human-readable label (e.g., "Max Position Size"). */
  label: string;
  /** Current value as a number. */
  current: number;
  /** Proposed new value as a number. */
  proposed: number;
  /** Percentage change: (proposed - current) / current * 100. */
  changePercent: number;
  /** True if absolute change exceeds 50% increase (changePercent > 50). */
  isLargeChange: boolean;
}

/**
 * Mapping of field keys to human-readable labels for display.
 */
export const riskSettingsLabels: Record<string, string> = {
  max_position_size: "Max Position Size",
  max_daily_loss: "Max Daily Loss",
  max_order_value: "Max Order Value",
  max_concentration_pct: "Max Concentration %",
  max_open_orders: "Max Open Orders",
};
