/**
 * Exports feature constants — centralized values for status styling, labels, and API config.
 *
 * Purpose:
 *   Single source of truth for export status badge styling, type labels,
 *   filter options, and API retry parameters used across the Exports feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 */

import type { ExportStatus, ExportType } from "@/types/exports";

// ---------------------------------------------------------------------------
// Status badge styling
// ---------------------------------------------------------------------------

/**
 * Tailwind class sets for export status badges.
 *
 * pending=blue, processing=amber, complete=emerald, failed=red per M31 spec.
 */
export const EXPORT_STATUS_CLASSES: Record<ExportStatus, string> = {
  pending: "bg-blue-100 text-blue-800 ring-blue-600/20",
  processing: "bg-amber-100 text-amber-900 ring-amber-600/30",
  complete: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  failed: "bg-red-100 text-red-800 ring-red-600/20",
};

/** Human-readable export status labels. */
export const EXPORT_STATUS_LABELS: Record<ExportStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  complete: "Complete",
  failed: "Failed",
};

/** Human-readable export type labels. */
export const EXPORT_TYPE_LABELS: Record<ExportType, string> = {
  trades: "Trades",
  runs: "Runs",
  artifacts: "Artifacts",
};

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/** Default page size for the export list. */
export const EXPORTS_DEFAULT_PAGE_SIZE = 25;

/** Maximum page size accepted by the backend. */
export const EXPORTS_MAX_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// API & retry (CLAUDE.md §9)
// ---------------------------------------------------------------------------

/** Maximum retry attempts for exports API GET calls. */
export const EXPORTS_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const EXPORTS_API_RETRY_BASE_DELAY_MS = 1000;

/** Symmetric jitter factor for retry backoff. */
export const EXPORTS_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Polling for in-progress exports
// ---------------------------------------------------------------------------

/** Poll interval (ms) while an export is processing. */
export const EXPORT_POLL_INTERVAL_MS = 2000;

/** Maximum poll attempts before giving up. */
export const EXPORT_MAX_POLL_ATTEMPTS = 150; // 5 minutes at 2s intervals

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_CREATE_EXPORT = "exports.create_export";
export const OP_LIST_EXPORTS = "exports.list_exports";
export const OP_GET_EXPORT = "exports.get_export";
export const OP_DOWNLOAD_EXPORT = "exports.download_export";
export const OP_RETRY_ATTEMPT = "exports.retry_attempt";
export const OP_VALIDATION_FAILURE = "exports.validation_failure";
