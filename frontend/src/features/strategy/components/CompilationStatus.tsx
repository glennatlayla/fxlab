/**
 * CompilationStatus — display strategy compilation pipeline progress.
 *
 * Purpose:
 *   Render a visual timeline of compilation stages with status indicators
 *   (running spinner, completed checkmark, failed X, pending clock, skipped icon).
 *   Shows error messages for failed stages, duration for completed stages, and
 *   overall compilation status.
 *
 * Responsibilities:
 *   - Render each compilation stage as a row with label and status icon.
 *   - Show appropriate icon based on stage status (spinner, checkmark, X, clock, skip).
 *   - Display error message for failed stages.
 *   - Display duration (ms) for completed stages.
 *   - Show overall compilation status and styling.
 *   - Apply appropriate color classes based on stage status.
 *
 * Does NOT:
 *   - Manage compilation state or trigger compilation.
 *   - Fetch compilation data (passed as prop).
 *
 * Dependencies:
 *   - CompilationRun type from @/types/strategy
 *   - lucide-react icons (CheckCircle, AlertCircle, Clock, Loader2, SkipForward)
 *
 * Example:
 *   const compilation: CompilationRun = {
 *     id: "compile-1",
 *     strategyId: "strategy-1",
 *     overallStatus: "completed",
 *     stages: [
 *       { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
 *     ],
 *   };
 *   <CompilationStatus compilation={compilation} />
 */

import type { CompilationRun } from "@/types/strategy";

interface CompilationStatusProps {
  /** Compilation run data with stages and overall status. */
  compilation: CompilationRun;
}

export function CompilationStatus({ compilation }: CompilationStatusProps) {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return (
          <svg
            className="check h-5 w-5 text-success"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <path d="m9 11 3 3L22 4" />
          </svg>
        );
      case "running":
        return (
          <svg
            className="animate h-5 w-5 animate-spin text-info"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
          </svg>
        );
      case "failed":
        return (
          <svg
            className="x h-5 w-5 text-danger"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        );
      case "skipped":
        return (
          <svg
            className="h-5 w-5 text-surface-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polygon points="5 4 15 12 5 20 5 4" />
            <line x1="19" y1="5" x2="19" y2="19" />
          </svg>
        );
      case "pending":
        return (
          <svg
            className="h-5 w-5 text-surface-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        );
      default:
        return null;
    }
  };

  const getRowClasses = (status: string) => {
    const baseClasses = "rounded-lg p-4 border";
    switch (status) {
      case "completed":
        return `${baseClasses} border-success/20 bg-success/5`;
      case "running":
        return `${baseClasses} border-info/20 bg-info/5`;
      case "failed":
        return `${baseClasses} border-danger/20 bg-danger/5`;
      case "skipped":
        return `${baseClasses} border-surface-200 bg-surface-50 skipped`;
      case "pending":
        return `${baseClasses} border-surface-200 bg-surface-50`;
      default:
        return baseClasses;
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-surface-50 p-4">
        <p className="text-sm font-medium text-surface-900">
          Overall Status: {compilation.overallStatus}
        </p>
      </div>

      <div className="space-y-3">
        {compilation.stages.map((stage) => (
          <div key={stage.name} className={getRowClasses(stage.status)}>
            <div
              className={`flex items-start gap-2 ${stage.status === "skipped" ? "skipped" : ""}`}
            >
              <div className="flex-shrink-0 pt-0.5">{getStatusIcon(stage.status)}</div>
              <p className="flex-1 text-sm font-medium text-surface-900">{stage.label}</p>
              {stage.error && <p className="mt-1 text-xs text-danger">{stage.error}</p>}
            </div>
            {stage.status === "completed" && stage.durationMs !== undefined && (
              <p className="mt-1 text-xs text-surface-600">Duration: {stage.durationMs} ms</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
