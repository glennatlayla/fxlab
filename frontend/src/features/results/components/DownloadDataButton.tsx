/**
 * DownloadDataButton — generic download trigger button.
 *
 * Purpose:
 *   Provides a reusable button component for triggering data exports
 *   across the Results Explorer (trade blotter, trial summary, etc.).
 *
 * Responsibilities:
 *   - Render a download button with configurable label.
 *   - Show loading/disabled state during active downloads.
 *   - Delegate actual download logic to the onDownload callback.
 *
 * Does NOT:
 *   - Perform file I/O or network requests.
 *   - Know about specific data formats or schemas.
 *
 * Dependencies:
 *   - DownloadDataButtonProps from ../types.
 */

import type { DownloadDataButtonProps } from "../types";

/**
 * Render a download button.
 *
 * Args:
 *   onDownload: Callback triggered on click.
 *   label: Optional button text (defaults to "Download").
 *   isLoading: Whether a download is in progress.
 *
 * Returns:
 *   Button element.
 */
export function DownloadDataButton({
  onDownload,
  label = "Download",
  isLoading = false,
}: DownloadDataButtonProps) {
  return (
    <button
      type="button"
      onClick={onDownload}
      disabled={isLoading}
      aria-busy={isLoading ? "true" : undefined}
      className="inline-flex items-center gap-1.5 rounded-md bg-slate-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isLoading ? (
        <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      ) : (
        <svg
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
          />
        </svg>
      )}
      {label}
    </button>
  );
}
