/**
 * Artifacts feature constants — centralized values for styling, labels, and API config.
 *
 * Purpose:
 *   Single source of truth for artifact type badge styling, human-readable labels,
 *   filter options, and API retry parameters used across the Artifacts feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 */

import type { ArtifactType } from "@/types/artifacts";

// ---------------------------------------------------------------------------
// Artifact type labels & styling
// ---------------------------------------------------------------------------

/** Human-readable artifact type labels. */
export const ARTIFACT_TYPE_LABELS: Record<ArtifactType, string> = {
  compiled_strategy: "Compiled Strategy",
  backtest_result: "Backtest Result",
  optimization_result: "Optimization Result",
  holdout_result: "Holdout Result",
  readiness_report: "Readiness Report",
  export_bundle: "Export Bundle",
};

/** Tailwind class sets for artifact type badges. */
export const ARTIFACT_TYPE_BADGE_CLASSES: Record<ArtifactType, string> = {
  compiled_strategy: "bg-blue-100 text-blue-800 ring-blue-600/20",
  backtest_result: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  optimization_result: "bg-purple-100 text-purple-800 ring-purple-600/20",
  holdout_result: "bg-amber-100 text-amber-900 ring-amber-600/30",
  readiness_report: "bg-pink-100 text-pink-800 ring-pink-600/20",
  export_bundle: "bg-slate-100 text-slate-800 ring-slate-600/20",
};

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/** Default page size for the artifact browser. */
export const DEFAULT_PAGE_SIZE = 25;

/** Maximum page size accepted by the backend. */
export const MAX_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// API & retry (CLAUDE.md §9)
// ---------------------------------------------------------------------------

/** Maximum retry attempts for artifacts API GET calls. */
export const ARTIFACTS_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const ARTIFACTS_API_RETRY_BASE_DELAY_MS = 1000;

/** Symmetric jitter factor for retry backoff. */
export const ARTIFACTS_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_LIST_ARTIFACTS = "artifacts.list_artifacts";
export const OP_DOWNLOAD_ARTIFACT = "artifacts.download_artifact";
export const OP_RETRY_ATTEMPT = "artifacts.retry_attempt";
export const OP_VALIDATION_FAILURE = "artifacts.validation_failure";

// ---------------------------------------------------------------------------
// File size formatting
// ---------------------------------------------------------------------------

/**
 * Format bytes into human-readable size (KB, MB, GB).
 *
 * Args:
 *   bytes: Number of bytes.
 *
 * Returns:
 *   Formatted string (e.g., "2.5 MB").
 *
 * Example:
 *   formatFileSize(1024) → "1.0 KB"
 *   formatFileSize(2097152) → "2.0 MB"
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";

  const units = ["B", "KB", "MB", "GB"];
  const index = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = bytes / Math.pow(1024, index);

  return `${size.toFixed(1)} ${units[index]}`;
}
