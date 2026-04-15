/**
 * PreflightFailureDisplay — structured rejection reasons per spec §8.3.
 *
 * Purpose:
 *   Render preflight validation failures with blocker details, owner
 *   information, and next-step actions. Uses the BLOCKER_CODE_REGISTRY
 *   for human-readable copy.
 *
 * Responsibilities:
 *   - Display each blocker with plain-language description.
 *   - Show blocker owner for resolution routing.
 *   - Provide next-step action buttons.
 *   - Emit structured onNextStep callback (no console.warn).
 *
 * Does NOT:
 *   - Execute preflight checks (backend does this).
 *   - Navigate to blocker resolution pages (emits callbacks to parent).
 *   - Contain logging (parent handles via RunLogger if needed).
 */

import { BLOCKER_CODE_REGISTRY } from "@/types/run";
import type { BlockerDetail } from "@/types/run";
import type { PreflightFailureDisplayProps, BlockerCardProps } from "../types";

/**
 * Render a single blocker card within the preflight display.
 *
 * Args:
 *   blocker: Blocker detail record.
 *   onNextStepClick: Callback when next-step action is clicked.
 */
function BlockerCard({ blocker, onNextStepClick }: BlockerCardProps) {
  const registryEntry = BLOCKER_CODE_REGISTRY[blocker.code];
  const plainLanguage = registryEntry?.plainLanguage ?? blocker.message;
  const nextStepDescription = registryEntry?.nextStepDescription ?? blocker.next_step;

  return (
    <div className="rounded-md border border-red-800 bg-red-900/20 p-4" data-testid="blocker-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="rounded bg-red-800 px-1.5 py-0.5 font-mono text-xs text-red-200">
              {blocker.code}
            </span>
          </div>
          <p className="mt-1.5 text-sm text-gray-300">{plainLanguage}</p>
          <div className="mt-2 text-xs text-gray-400">
            Owner: <span className="text-gray-300">{blocker.blocker_owner}</span>
          </div>
        </div>
        <button
          type="button"
          className="flex-shrink-0 rounded-md bg-gray-700 px-3 py-1.5 text-xs font-medium text-gray-200 transition-colors hover:bg-gray-600"
          onClick={() => onNextStepClick(blocker)}
          data-testid="blocker-next-step"
        >
          {nextStepDescription}
        </button>
      </div>
    </div>
  );
}

/**
 * Render preflight failure display with all blockers.
 *
 * Args:
 *   preflightResults: Array of preflight results.
 *   onNextStep: Optional callback when a blocker next-step is clicked.
 *     Receives the blocker detail and the registry next-step key.
 *     If omitted, next-step buttons are still rendered but no-op.
 *   className: Optional additional CSS class names.
 */
export function PreflightFailureDisplay({
  preflightResults,
  onNextStep,
  className = "",
}: PreflightFailureDisplayProps) {
  // Collect all blockers from failed preflight results
  const failedResults = preflightResults.filter((r) => !r.passed);
  const allBlockers = failedResults.flatMap((r) => r.blockers);

  if (allBlockers.length === 0) return null;

  const handleNextStepClick = (blocker: BlockerDetail) => {
    const entry = BLOCKER_CODE_REGISTRY[blocker.code];
    if (onNextStep && entry) {
      onNextStep(blocker, entry.nextStepKey);
    }
  };

  return (
    <div className={`space-y-3 ${className}`.trim()} data-testid="preflight-failure-display">
      <div className="flex items-center gap-2 text-sm font-semibold text-red-400">
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
            clipRule="evenodd"
          />
        </svg>
        Preflight Failed — {allBlockers.length} blocker{allBlockers.length !== 1 ? "s" : ""}
      </div>
      {allBlockers.map((blocker, index) => (
        <BlockerCard
          key={`${blocker.code}-${index}`}
          blocker={blocker}
          onNextStepClick={handleNextStepClick}
        />
      ))}
    </div>
  );
}
