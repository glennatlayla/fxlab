/**
 * Risk settings utility functions.
 *
 * Purpose:
 *   Provide helper functions for risk settings calculations and transformations.
 *
 * Responsibilities:
 *   - Calculate change diffs between current and proposed settings.
 *   - Detect large changes (>50% increase).
 *   - Format numeric values for display.
 *
 * Does NOT:
 *   - Contain business logic or validation.
 *   - Make API calls.
 *   - Manage state.
 *
 * Dependencies:
 *   - types: RiskSettings, RiskSettingsUpdate, RiskSettingsDiff, riskSettingsLabels.
 *
 * Error conditions:
 *   - None; pure utility functions with sensible defaults.
 *
 * Example:
 *   const diffs = calculateDiffs(current, updates);
 *   const pct = calculateChangePercent(100, 150);  // 50%
 */

import type { RiskSettings, RiskSettingsUpdate, RiskSettingsDiff } from "./types";
import { riskSettingsLabels } from "./types";

/**
 * Calculate the percentage change from current to proposed value.
 *
 * Args:
 *   current: Current numeric value.
 *   proposed: Proposed numeric value.
 *
 * Returns:
 *   Percentage change as a number. For example, 100 → 150 returns 50.
 *   If current is 0 (unlimited), returns 0 (no meaningful % change).
 *
 * Example:
 *   calculateChangePercent(100, 150) → 50
 *   calculateChangePercent(100, 50) → -50
 *   calculateChangePercent(0, 100) → 0 (unlimited to limit)
 */
export function calculateChangePercent(current: number, proposed: number): number {
  if (current === 0) {
    return 0;
  }
  return ((proposed - current) / current) * 100;
}

/**
 * Calculate diffs for all changed fields.
 *
 * Args:
 *   current: Current risk settings.
 *   updates: Partial updates object.
 *
 * Returns:
 *   Array of RiskSettingsDiff objects for each changed field.
 *   Empty array if no fields changed.
 *
 * Example:
 *   const current = { max_position_size: "10000", ... };
 *   const updates = { max_position_size: "15000" };
 *   const diffs = calculateDiffs(current, updates);
 *   // [{ field: "max_position_size", label: "Max Position Size", current: 10000, proposed: 15000, changePercent: 50, isLargeChange: true }]
 */
export function calculateDiffs(
  current: RiskSettings,
  updates: RiskSettingsUpdate,
): RiskSettingsDiff[] {
  const diffs: RiskSettingsDiff[] = [];

  // Map of field keys to current numeric values.
  const currentNumeric: Record<string, number> = {
    max_position_size: parseFloat(current.max_position_size),
    max_daily_loss: parseFloat(current.max_daily_loss),
    max_order_value: parseFloat(current.max_order_value),
    max_concentration_pct: parseFloat(current.max_concentration_pct),
    max_open_orders: current.max_open_orders,
  };

  // Iterate over each update and calculate the diff.
  for (const [field, proposedValue] of Object.entries(updates)) {
    if (proposedValue === undefined) continue;

    const currentValue = currentNumeric[field];
    if (currentValue === undefined) continue;

    const proposedNumeric =
      typeof proposedValue === "string" ? parseFloat(proposedValue) : proposedValue;

    // Skip if values are the same.
    if (currentValue === proposedNumeric) continue;

    const changePercent = calculateChangePercent(currentValue, proposedNumeric);
    const isLargeChange = changePercent > 50;

    diffs.push({
      field,
      label: riskSettingsLabels[field] || field,
      current: currentValue,
      proposed: proposedNumeric,
      changePercent,
      isLargeChange,
    });
  }

  return diffs;
}
