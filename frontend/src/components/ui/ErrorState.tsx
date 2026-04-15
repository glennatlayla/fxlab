/**
 * ErrorState — error display for failed data fetches or unexpected errors.
 *
 * Example:
 *   <ErrorState message="Failed to load feeds" onRetry={() => refetch()} />
 */

import { AlertTriangle } from "lucide-react";

interface ErrorStateProps {
  /** Error message to display. */
  message: string;
  /** Optional retry callback. Renders a Retry button when provided. */
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center" role="alert">
      <AlertTriangle className="h-12 w-12 text-danger" />
      <h3 className="text-lg font-medium text-surface-700">Something went wrong</h3>
      <p className="max-w-sm text-sm text-surface-500">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 rounded-md border border-surface-300 px-4 py-1.5 text-sm font-medium
            text-surface-700 hover:bg-surface-100"
        >
          Retry
        </button>
      )}
    </div>
  );
}
