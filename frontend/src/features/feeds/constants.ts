/**
 * Feeds feature constants — centralized values for status styling, labels, and API config.
 *
 * Purpose:
 *   Single source of truth for feed health badge styling, anomaly labels,
 *   filter options, and API retry parameters used across the Feeds feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 */

import type { FeedHealthStatus, AnomalyType, ConnectivityStatus } from "@/types/feeds";

// ---------------------------------------------------------------------------
// Health badge styling
// ---------------------------------------------------------------------------

/**
 * Tailwind class sets for feed health status badges.
 *
 * Per M30 spec: degraded feeds MUST display a non-neutral colour and the
 * badge MUST NOT be suppressible by the operator.
 */
export const FEED_HEALTH_BADGE_CLASSES: Record<FeedHealthStatus, string> = {
  healthy: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  degraded: "bg-amber-100 text-amber-900 ring-amber-600/30",
  quarantined: "bg-red-100 text-red-800 ring-red-600/20",
  offline: "bg-zinc-200 text-zinc-800 ring-zinc-600/20",
};

/** Human-readable feed health status labels. */
export const FEED_HEALTH_LABELS: Record<FeedHealthStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  quarantined: "Quarantined",
  offline: "Offline",
};

/** Human-readable anomaly type labels. */
export const ANOMALY_TYPE_LABELS: Record<AnomalyType, string> = {
  gap: "Gap",
  spike: "Spike",
  stale: "Stale",
  duplicate: "Duplicate",
  out_of_order: "Out of Order",
};

/** Human-readable connectivity status labels. */
export const CONNECTIVITY_STATUS_LABELS: Record<ConnectivityStatus, string> = {
  ok: "OK",
  failed: "Failed",
  timeout: "Timeout",
};

/** Tailwind classes for connectivity status badges. */
export const CONNECTIVITY_STATUS_CLASSES: Record<ConnectivityStatus, string> = {
  ok: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  failed: "bg-red-100 text-red-800 ring-red-600/20",
  timeout: "bg-amber-100 text-amber-900 ring-amber-600/30",
};

// ---------------------------------------------------------------------------
// Filter options
// ---------------------------------------------------------------------------

export const FEED_HEALTH_FILTER_OPTIONS = [
  { value: "all", label: "All Feeds" },
  { value: "healthy", label: "Healthy" },
  { value: "degraded", label: "Degraded" },
  { value: "quarantined", label: "Quarantined" },
  { value: "offline", label: "Offline" },
] as const;

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/** Default page size for the feed list. */
export const FEEDS_DEFAULT_PAGE_SIZE = 25;

/** Maximum page size accepted by the backend. */
export const FEEDS_MAX_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// API & retry (CLAUDE.md §9)
// ---------------------------------------------------------------------------

/** Maximum retry attempts for feeds API GET calls. */
export const FEEDS_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const FEEDS_API_RETRY_BASE_DELAY_MS = 1000;

/** Symmetric jitter factor for retry backoff. */
export const FEEDS_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_LIST_FEEDS = "feeds.list_feeds";
export const OP_GET_FEED = "feeds.get_feed";
export const OP_LIST_FEED_HEALTH = "feeds.list_feed_health";
export const OP_RETRY_ATTEMPT = "feeds.retry_attempt";
export const OP_VALIDATION_FAILURE = "feeds.validation_failure";
