/**
 * Parity feature constants — centralized values for severity styling, labels, and API config.
 *
 * Purpose:
 *   Single source of truth for parity severity badge styling, status labels,
 *   and API retry parameters used across the Parity feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 */

import type { ParityEventSeverity } from "@/types/parity";

// ---------------------------------------------------------------------------
// Severity badge styling
// ---------------------------------------------------------------------------

/**
 * Tailwind class sets for parity event severity badges.
 *
 * INFO (blue): Informational discrepancies.
 * WARNING (amber): Significant deviations requiring review.
 * CRITICAL (red): Severe parity breaches requiring immediate action.
 */
export const PARITY_SEVERITY_BADGE_CLASSES: Record<ParityEventSeverity, string> = {
  INFO: "bg-blue-100 text-blue-800 ring-blue-600/20",
  WARNING: "bg-amber-100 text-amber-900 ring-amber-600/30",
  CRITICAL: "bg-red-100 text-red-800 ring-red-600/20",
};

/** Human-readable parity severity labels. */
export const PARITY_SEVERITY_LABELS: Record<ParityEventSeverity, string> = {
  INFO: "Info",
  WARNING: "Warning",
  CRITICAL: "Critical",
};

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/** Default page size for the parity event list. */
export const PARITY_DEFAULT_PAGE_SIZE = 20;

/** Maximum page size accepted by the backend. */
export const PARITY_MAX_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// API & retry (CLAUDE.md §9)
// ---------------------------------------------------------------------------

/** Maximum retry attempts for parity API GET calls. */
export const PARITY_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const PARITY_API_RETRY_BASE_DELAY_MS = 1000;

/** Symmetric jitter factor for retry backoff. */
export const PARITY_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_LIST_EVENTS = "parity.list_events";
export const OP_GET_EVENT = "parity.get_event";
export const OP_GET_SUMMARY = "parity.get_summary";
export const OP_RETRY_ATTEMPT = "parity.retry_attempt";
export const OP_VALIDATION_FAILURE = "parity.validation_failure";
