/**
 * ResultsMetricTile — reusable metric display tile.
 *
 * Purpose:
 *   Display a single metric (label + value) with semantic color coding
 *   based on sentiment (positive/negative/neutral/warning). Used in
 *   ResultsSummaryCard for key performance indicators.
 *
 * Responsibilities:
 *   - Render metric label and value.
 *   - Apply color based on sentiment prop.
 *   - Optionally render an icon from lucide-react.
 *   - Maintain compact mobile-first layout.
 *
 * Does NOT:
 *   - Fetch or calculate metric values (parent component responsibility).
 *   - Format values (parent formats before passing).
 *   - Handle click events or navigation.
 *
 * Dependencies:
 *   - React (ElementType from "react").
 *   - lucide-react icons (optional).
 *   - Tailwind CSS.
 *
 * Example:
 *   <ResultsMetricTile
 *     label="Sharpe Ratio"
 *     value="1.85"
 *     sentiment="positive"
 *     icon={TrendingUp}
 *   />
 */

import type { ElementType } from "react";

/**
 * Props for the ResultsMetricTile component.
 */
export interface ResultsMetricTileProps {
  /** Metric label (e.g., "Sharpe Ratio"). */
  label: string;
  /** Formatted value string (e.g., "1.85", "+12.3%"). */
  value: string;
  /** Semantic color: "positive" | "negative" | "neutral" | "warning". */
  sentiment?: "positive" | "negative" | "neutral" | "warning";
  /** Optional icon component from lucide-react. */
  icon?: ElementType;
}

/**
 * Map sentiment to Tailwind color class.
 *
 * Args:
 *   sentiment: The sentiment value.
 *
 * Returns:
 *   Tailwind color class string.
 */
function getSentimentColor(sentiment?: string): string {
  switch (sentiment) {
    case "positive":
      return "text-green-400";
    case "negative":
      return "text-red-400";
    case "warning":
      return "text-amber-400";
    case "neutral":
    default:
      return "text-surface-700";
  }
}

/**
 * Render a metric tile.
 *
 * Args:
 *   label: Metric label.
 *   value: Formatted value string.
 *   sentiment: Color sentiment (defaults to neutral).
 *   icon: Optional icon component.
 *
 * Returns:
 *   Rendered tile element.
 */
export function ResultsMetricTile({
  label,
  value,
  sentiment = "neutral",
  icon: Icon,
}: ResultsMetricTileProps) {
  const colorClass = getSentimentColor(sentiment);

  return (
    <div
      className="flex flex-col items-start gap-1 rounded-md bg-surface-900 p-3"
      data-sentiment={sentiment}
    >
      {/* Label and optional icon */}
      <div className="flex items-center gap-1">
        {Icon && (
          <Icon
            className="h-4 w-4 text-surface-500"
            data-testid="metric-tile-icon"
            aria-hidden="true"
          />
        )}
        <span className="text-xs font-medium text-surface-500">{label}</span>
      </div>

      {/* Value */}
      <span className={`text-lg font-semibold ${colorClass}`}>{value}</span>
    </div>
  );
}
