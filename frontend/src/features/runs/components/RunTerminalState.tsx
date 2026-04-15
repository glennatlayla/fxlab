/**
 * RunTerminalState — displayed when run reaches a terminal status.
 *
 * Purpose:
 *   Render appropriate UI for each terminal status:
 *     - complete → results link
 *     - failed → error message + retry button
 *     - cancelled → cancellation reason
 *
 * Responsibilities:
 *   - Display terminal state messaging.
 *   - Provide action buttons (view results, retry, etc.).
 *
 * Does NOT:
 *   - Determine terminal status (parent provides run record).
 *   - Handle retry logic (emits callback to parent).
 */

import { RUN_STATUS } from "@/types/run";
import type { RunTerminalStateProps } from "../types";

/**
 * Render the terminal state display.
 *
 * Args:
 *   run: Run record in a terminal status.
 *   onRetry: Callback to retry a failed run.
 */
export function RunTerminalState({ run, onRetry }: RunTerminalStateProps) {
  if (run.status === RUN_STATUS.COMPLETE) {
    return (
      <div
        className="rounded-lg border border-green-800 bg-green-900/20 p-4"
        data-testid="run-terminal-complete"
      >
        <div className="flex items-center gap-2 text-green-400">
          <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-semibold">Run Complete</span>
        </div>
        {run.result_uri && (
          <div className="mt-3">
            <a
              href={run.result_uri}
              className="inline-flex items-center gap-1.5 rounded-md bg-green-700 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-green-600"
              data-testid="results-link"
            >
              View Results
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                />
              </svg>
            </a>
          </div>
        )}
      </div>
    );
  }

  if (run.status === RUN_STATUS.FAILED) {
    return (
      <div
        className="rounded-lg border border-red-800 bg-red-900/20 p-4"
        data-testid="run-terminal-failed"
      >
        <div className="flex items-center gap-2 text-red-400">
          <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-semibold">Run Failed</span>
        </div>
        {run.error_message && <p className="mt-2 text-sm text-gray-300">{run.error_message}</p>}
        <div className="mt-3">
          <button
            type="button"
            className="rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-red-600"
            onClick={onRetry}
            data-testid="retry-button"
          >
            Retry Run
          </button>
        </div>
      </div>
    );
  }

  if (run.status === RUN_STATUS.CANCELLED) {
    return (
      <div
        className="rounded-lg border border-gray-700 bg-gray-800 p-4"
        data-testid="run-terminal-cancelled"
      >
        <div className="flex items-center gap-2 text-gray-400">
          <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM6.75 9.25a.75.75 0 000 1.5h6.5a.75.75 0 000-1.5h-6.5z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-semibold">Run Cancelled</span>
        </div>
        {run.cancellation_reason && (
          <p className="mt-2 text-sm text-gray-300">{run.cancellation_reason}</p>
        )}
      </div>
    );
  }

  return null;
}
