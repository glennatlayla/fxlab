/**
 * LoadingState — centered spinner with optional message.
 *
 * Use when a page or section is loading data.
 *
 * Example:
 *   <LoadingState message="Loading feeds…" />
 */

interface LoadingStateProps {
  /** Optional message displayed below the spinner. */
  message?: string;
}

export function LoadingState({ message = "Loading…" }: LoadingStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16" role="status">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-500 border-t-transparent" />
      <p className="text-sm text-surface-500">{message}</p>
    </div>
  );
}
