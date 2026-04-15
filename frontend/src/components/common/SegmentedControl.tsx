/**
 * SegmentedControl — Reusable radio-button-like horizontal selector.
 *
 * Purpose:
 *   Provide a mobile-friendly segmented control (pill selector) for
 *   choosing between a fixed set of mutually exclusive options.
 *   Used in the backtest form for time interval selection.
 *
 * Responsibilities:
 *   - Render horizontal row of toggle buttons.
 *   - Highlight active option with brand color.
 *   - Call onChange only when a new option is selected.
 *   - Support keyboard navigation and activation (Tab, Enter, Space).
 *   - Implement radio group semantics with ARIA roles.
 *
 * Does NOT:
 *   - Manage state; receives value as a prop.
 *   - Render dropdown or other picker variants.
 *   - Handle horizontal scrolling for many options.
 *
 * Dependencies:
 *   - React (ReactNode, useState, CSSProperties).
 *   - clsx (CSS class composition).
 *
 * Error conditions:
 *   - None; invalid options gracefully render.
 *
 * Example:
 *   <SegmentedControl
 *     options={[
 *       { value: "1d", label: "1 Day" },
 *       { value: "1w", label: "1 Week" },
 *     ]}
 *     value="1d"
 *     onChange={(val) => setInterval(val)}
 *   />
 */

import React from "react";
import clsx from "clsx";

/** Option in the segmented control. */
export interface SegmentedControlOption<T extends string = string> {
  /** Unique identifier for the option. */
  value: T;
  /** Display label shown to the user. */
  label: string | React.ReactNode;
}

/** Props for SegmentedControl component. */
export interface SegmentedControlProps<T extends string = string> {
  /** Array of selectable options. */
  options: readonly SegmentedControlOption<T>[];
  /** Currently selected option value. */
  value: T;
  /** Callback when a different option is selected. */
  onChange: (value: T) => void;
  /** Optional additional CSS classes for the container. */
  className?: string;
  /** Optional test ID for the container. */
  "data-testid"?: string;
  /** Optional id for the container (for accessibility). */
  id?: string;
}

/**
 * SegmentedControl component.
 *
 * Renders a horizontal row of toggle buttons with pill styling.
 * The active button is highlighted with brand-600 background.
 * Keyboard accessible with full Tab, Enter, and Space support.
 *
 * Example:
 *   const [interval, setInterval] = useState<TimeInterval>("1d");
 *   return (
 *     <SegmentedControl
 *       options={TIME_INTERVALS}
 *       value={interval}
 *       onChange={setInterval}
 *     />
 *   );
 */
export function SegmentedControl<T extends string = string>({
  options,
  value,
  onChange,
  className,
  "data-testid": testId,
  id,
}: SegmentedControlProps<T>): React.ReactElement {
  return (
    <div
      id={id}
      role="radiogroup"
      className={clsx("inline-flex items-center gap-2 rounded-lg bg-surface-100 p-1", className)}
      data-testid={testId}
    >
      {options.map((option) => {
        const isActive = option.value === value;

        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-pressed={isActive}
            aria-checked={isActive}
            onClick={() => {
              // Only call onChange if selecting a different option.
              if (option.value !== value) {
                onChange(option.value);
              }
            }}
            className={clsx(
              "px-3 py-2 rounded-full font-medium text-sm transition-all duration-200 whitespace-nowrap",
              isActive
                ? "bg-brand-600 text-white shadow-sm"
                : "bg-transparent text-surface-600 hover:text-surface-900 active:bg-surface-200",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
