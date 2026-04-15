/**
 * RiskSettingsCard — Display current risk limits with inline editing.
 *
 * Purpose:
 *   Show current risk limit values in a mobile-friendly card layout.
 *   Allow inline editing of individual fields with immediate feedback.
 *   Color-code limits based on conservativeness (green=safe, amber=moderate, red=aggressive).
 *
 * Responsibilities:
 *   - Display all risk limit fields with current values.
 *   - Show edit pencil icon for each field.
 *   - Enable inline edit mode on pencil click.
 *   - Confirm edits on Enter or blur; cancel on Escape.
 *   - Color-code limits: green for high/conservative, amber for moderate, red for low/aggressive.
 *   - Call onFieldChange callback for confirmed changes.
 *   - Disable editing when isLoading=true.
 *
 * Does NOT:
 *   - Make API calls (parent is responsible).
 *   - Validate values (parent does this).
 *   - Manage overall state (receives settings via props).
 *
 * Dependencies:
 *   - React (useState, ReactNode)
 *   - RiskSettings type
 *   - lucide-react (PencilIcon)
 *   - Tailwind CSS, clsx
 *
 * Error conditions:
 *   - None; gracefully handles missing settings.
 *
 * Example:
 *   <RiskSettingsCard
 *     settings={currentSettings}
 *     onFieldChange={(field, value) => updatePendingChange(field, value)}
 *     isLoading={false}
 *   />
 */

import React, { useState } from "react";
import { Pencil } from "lucide-react";
import clsx from "clsx";
import type { RiskSettings } from "../types";
import { riskSettingsLabels } from "../types";

export interface RiskSettingsCardProps {
  /** Current risk settings to display. */
  settings: RiskSettings;
  /** Callback when user edits a field: (fieldKey, newValue) => void. */
  onFieldChange: (field: string, value: string | number) => void;
  /** Whether the card is in loading state (disables editing). */
  isLoading?: boolean;
}

/**
 * Determine the color class for a numeric limit based on its magnitude.
 *
 * Args:
 *   value: Numeric limit value.
 *   fieldType: Type of field for context-specific thresholds.
 *
 * Returns:
 *   CSS class name for background color: "bg-green-50" (conservative),
 *   "bg-amber-50" (moderate), or "bg-red-50" (aggressive).
 *
 * Logic:
 *   - Green: high/unlimited limits (safe).
 *   - Amber: moderate limits (watch closely).
 *   - Red: low/restrictive limits (aggressive risk control).
 */
function getColorClass(value: number, fieldType: string): string {
  // For percentage fields, use different thresholds.
  if (fieldType === "max_concentration_pct") {
    if (value === 0 || value > 50) return "bg-green-50";
    if (value >= 25) return "bg-amber-50";
    return "bg-red-50";
  }

  // For absolute value limits.
  if (value === 0) return "bg-green-50"; // Unlimited is safe
  if (value > 100000) return "bg-green-50"; // High limit is conservative
  if (value >= 10000) return "bg-amber-50"; // Moderate limit
  return "bg-red-50"; // Low limit is aggressive
}

/**
 * RiskSettingsCard component.
 *
 * Renders a mobile-friendly card with all risk limit fields. Each field
 * has an edit pencil icon. Clicking the pencil enables inline editing.
 * Changes are confirmed on Enter/blur and reverted on Escape.
 *
 * Example:
 *   <RiskSettingsCard
 *     settings={settings}
 *     onFieldChange={handleChange}
 *     isLoading={false}
 *   />
 */
export function RiskSettingsCard({
  settings,
  onFieldChange,
  isLoading = false,
}: RiskSettingsCardProps): React.ReactElement {
  // Track which field is being edited and its temporary value.
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState<string>("");

  /**
   * Start editing a field.
   */
  const startEdit = (field: string, value: string | number) => {
    setEditingField(field);
    setEditingValue(String(value));
  };

  /**
   * Cancel edit and return to display mode.
   */
  const cancelEdit = () => {
    setEditingField(null);
    setEditingValue("");
  };

  /**
   * Confirm edit and call onFieldChange.
   */
  const confirmEdit = () => {
    if (editingField === null) return;

    // For numeric fields (max_open_orders), convert to number.
    const value = editingField === "max_open_orders" ? parseInt(editingValue, 10) : editingValue;

    onFieldChange(editingField, value);
    cancelEdit();
  };

  /**
   * Handle key down in edit field.
   * Enter: confirm, Escape: cancel.
   */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      confirmEdit();
    } else if (e.key === "Escape") {
      cancelEdit();
    }
  };

  // Define fields to render in order.
  const fields: Array<{
    key: string;
    label: string;
    value: string | number;
    type: "text" | "number";
  }> = [
    {
      key: "max_position_size",
      label: riskSettingsLabels.max_position_size,
      value: settings.max_position_size,
      type: "text",
    },
    {
      key: "max_daily_loss",
      label: riskSettingsLabels.max_daily_loss,
      value: settings.max_daily_loss,
      type: "text",
    },
    {
      key: "max_order_value",
      label: riskSettingsLabels.max_order_value,
      value: settings.max_order_value,
      type: "text",
    },
    {
      key: "max_concentration_pct",
      label: riskSettingsLabels.max_concentration_pct,
      value: settings.max_concentration_pct,
      type: "text",
    },
    {
      key: "max_open_orders",
      label: riskSettingsLabels.max_open_orders,
      value: settings.max_open_orders,
      type: "number",
    },
  ];

  return (
    <div className="rounded-lg border border-surface-200 bg-white p-4">
      {/* Header */}
      <h2 className="mb-4 text-lg font-semibold text-surface-900">Risk Limits</h2>

      {/* Fields list */}
      <div className="space-y-3">
        {fields.map((field) => {
          const numericValue =
            field.type === "number" ? (field.value as number) : parseFloat(String(field.value));
          const colorClass = getColorClass(numericValue, field.key);
          const isEditing = editingField === field.key;

          return (
            <div
              key={field.key}
              data-testid={`field-${field.key}`}
              className={clsx("rounded-lg p-3 transition-colors", colorClass)}
            >
              {/* Label and value row */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex-1">
                  <div className="text-sm font-medium text-surface-900">{field.label}</div>
                </div>

                {/* Display or edit mode */}
                {isEditing ? (
                  <input
                    autoFocus
                    type={field.type}
                    value={editingValue}
                    onChange={(e) => setEditingValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={confirmEdit}
                    className="w-24 flex-shrink-0 rounded border border-surface-300 bg-white px-2 py-1 text-right text-sm font-semibold text-surface-900 focus:border-brand-500 focus:outline-none"
                  />
                ) : (
                  <>
                    <div className="flex-shrink-0 text-right text-lg font-semibold text-surface-900">
                      {field.type === "number"
                        ? String(field.value)
                        : parseFloat(String(field.value)).toLocaleString("en-US")}
                    </div>

                    {/* Edit button */}
                    <button
                      onClick={() => startEdit(field.key, field.value)}
                      disabled={isLoading}
                      aria-label={`Edit ${field.label}`}
                      className={clsx(
                        "flex-shrink-0 rounded p-1.5 transition-colors",
                        isLoading
                          ? "cursor-not-allowed opacity-50"
                          : "hover:bg-surface-200 active:bg-surface-300",
                      )}
                    >
                      <Pencil className="h-4 w-4 text-surface-600" />
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Info text */}
      <p className="mt-4 text-xs text-surface-500">
        <span className="mr-2 inline-block rounded bg-green-50 px-1.5">Green</span>= Conservative
        limits,
        <span className="mx-2 inline-block rounded bg-amber-50 px-1.5">Amber</span>= Moderate,
        <span className="ml-2 inline-block rounded bg-red-50 px-1.5">Red</span>= Aggressive
      </p>
    </div>
  );
}
