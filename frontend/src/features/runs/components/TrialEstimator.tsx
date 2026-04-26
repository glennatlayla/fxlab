/**
 * TrialEstimator component for optimization form (FE-15).
 *
 * Purpose:
 * - Display estimated trial count for parameter grid
 * - Color-code severity based on trial count
 * - Show estimated duration warning for extreme counts
 * - Update reactively as parameters change
 *
 * Responsibilities:
 * - Calculate trial count from parameter ranges
 * - Classify severity and apply color styling
 * - Display human-readable trial estimates
 * - Warn when count approaches or exceeds limits
 *
 * Does NOT:
 * - Validate parameters (that's the parent form's job)
 * - Modify parameters
 * - Call APIs
 *
 * Dependencies:
 * - optimisation.ts for domain utilities
 * - lucide-react for icon
 * - Tailwind CSS for styling
 *
 * Example:
 *   <TrialEstimator
 *     parameters={[
 *       { name: 'ma_fast', min: 5, max: 20, step: 5 },
 *       { name: 'ma_slow', min: 20, max: 50, step: 10 },
 *     ]}
 *   />
 */

import React, { useMemo } from "react";
import { AlertTriangle } from "lucide-react";
import {
  estimateTrialCount,
  getTrialCountSeverity,
  getSeverityLabel,
  getSeverityBgClass,
} from "../optimisation";
import { exceedsSoftTrialCountLimit } from "../optimisation.validation";
import type { ParameterRange } from "../optimisation";

export interface TrialEstimatorProps {
  /** Array of parameter ranges to estimate over. */
  parameters: ParameterRange[];
  /** Optional CSS class names. */
  className?: string;
}

/**
 * TrialEstimator — visual indicator for trial count and severity.
 *
 * Displays:
 * - Total estimated trial count
 * - Severity badge (Fast/Moderate/Long/Very Long)
 * - Warning message if count > 10,000
 *
 * Updates reactively when parameters change.
 *
 * Example:
 *   <TrialEstimator
 *     parameters={formData.parameters}
 *     className="mt-4"
 *   />
 */
export function TrialEstimator({ parameters, className }: TrialEstimatorProps): React.ReactElement {
  const trialCount = useMemo(() => estimateTrialCount(parameters), [parameters]);

  const severity = useMemo(() => getTrialCountSeverity(trialCount), [trialCount]);

  const severityLabel = getSeverityLabel(severity);
  const bgClass = getSeverityBgClass(severity);
  const showWarning = exceedsSoftTrialCountLimit(trialCount);

  if (parameters.length === 0) {
    return (
      <div className={`rounded-lg border border-gray-200 bg-gray-50 p-4 ${className || ""}`}>
        <p className="text-sm text-gray-600">Add parameters to estimate trial count</p>
      </div>
    );
  }

  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-4 ${className || ""}`}>
      {/* Header with count and severity badge */}
      <div className="mb-3 flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-gray-600">Estimated trials</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{trialCount.toLocaleString()}</p>
        </div>

        {/* Severity badge */}
        <div
          className={`${bgClass} min-w-fit rounded-full px-4 py-2 text-sm font-semibold text-white`}
        >
          {severityLabel}
        </div>
      </div>

      {/* Warning for extreme counts */}
      {showWarning && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-600" />
          <p className="text-sm text-amber-900">
            Optimization with {trialCount.toLocaleString()} trials may take considerable time.
            Consider reducing parameter ranges or step sizes.
          </p>
        </div>
      )}
    </div>
  );
}
