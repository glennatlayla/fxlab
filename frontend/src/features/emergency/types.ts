/**
 * Emergency controls domain types.
 *
 * Purpose:
 *   Define TypeScript types for kill switch API responses and UI state,
 *   matching the backend contracts in libs.contracts.safety.
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
 *   const status: KillSwitchStatus = {
 *     scope: 'global',
 *     target_id: 'global',
 *     is_active: true,
 *     activated_at: '2026-04-11T10:00:00Z',
 *     activated_by: 'operator@fxlab.io',
 *     reason: 'Daily loss limit breached',
 *   };
 */

/**
 * Kill switch scope enum.
 */
export type KillSwitchScope = "global" | "strategy" | "symbol";

/**
 * Status of a kill switch at a specific scope and target.
 *
 * All timestamp fields are ISO 8601 strings (e.g., "2026-04-11T10:00:00Z").
 */
export interface KillSwitchStatus {
  scope: KillSwitchScope;
  target_id: string;
  is_active: boolean;
  activated_at: string | null;
  deactivated_at: string | null;
  activated_by: string | null;
  reason: string | null;
}

/**
 * Response from GET /kill-switch/status endpoint.
 * Returns a list of all active kill switches.
 */
export interface KillSwitchStatusResponse {
  data: KillSwitchStatus[];
}

/**
 * Response from POST /kill-switch/* activation endpoints.
 * Returns details of the halt event that was triggered.
 */
export interface HaltEventResponse {
  event_id: string;
  scope: KillSwitchScope;
  target_id: string;
  trigger: string;
  reason: string;
  activated_by: string;
  activated_at: string;
  confirmed_at: string | null;
  mtth_ms: number;
  orders_cancelled: number;
  positions_flattened: number;
}
