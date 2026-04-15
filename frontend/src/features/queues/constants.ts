/**
 * Queues feature constants — centralized values for contention scoring, styling, and API config.
 *
 * Purpose:
 *   Single source of truth for queue contention color thresholds, labels,
 *   and API retry parameters used across the Queues feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 */

// ---------------------------------------------------------------------------
// Contention score thresholds & styling
// ---------------------------------------------------------------------------

/**
 * Contention score threshold for "low" (green) status.
 *
 * Per M30 spec: scores ≤ 30 indicate healthy queue depth.
 */
export const CONTENTION_SCORE_LOW_MAX = 30;

/**
 * Contention score threshold for "medium" (amber) status.
 *
 * Scores > LOW_MAX and ≤ this value indicate moderate load.
 * Per M30 spec: scores ≤ 70 are amber/caution.
 */
export const CONTENTION_SCORE_MEDIUM_MAX = 70;

/**
 * Contention score threshold for "high" (red) status.
 *
 * Per M30 spec: scores > 70 indicate critical queue depth.
 */
export const CONTENTION_SCORE_HIGH_MIN = CONTENTION_SCORE_MEDIUM_MAX + 1;

/**
 * Tailwind class sets for queue contention badges.
 *
 * Low (green): healthy queue depth.
 * Medium (amber): approaching capacity; monitor closely.
 * High (red): critical; operator intervention recommended.
 */
export const CONTENTION_BADGE_CLASSES = {
  low: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  medium: "bg-amber-100 text-amber-900 ring-amber-600/30",
  high: "bg-red-100 text-red-800 ring-red-600/20",
} as const;

/** Human-readable contention level labels. */
export const CONTENTION_LEVEL_LABELS = {
  low: "Healthy",
  medium: "Caution",
  high: "Critical",
} as const;

/**
 * Determine contention level from a numeric score.
 *
 * Args:
 *   score: Numeric contention score (0–100).
 *
 * Returns:
 *   One of "low", "medium", "high".
 *
 * Example:
 *   getContentionLevel(25)  // → "low"
 *   getContentionLevel(60)  // → "medium"
 *   getContentionLevel(90)  // → "high"
 */
export function getContentionLevel(score: number): "low" | "medium" | "high" {
  if (score <= CONTENTION_SCORE_LOW_MAX) return "low";
  if (score <= CONTENTION_SCORE_MEDIUM_MAX) return "medium";
  return "high";
}

// ---------------------------------------------------------------------------
// API & retry (CLAUDE.md §9)
// ---------------------------------------------------------------------------

/** Maximum retry attempts for queues API GET calls. */
export const QUEUES_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const QUEUES_API_RETRY_BASE_DELAY_MS = 1000;

/** Symmetric jitter factor for retry backoff. */
export const QUEUES_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_LIST_QUEUES = "queues.list_queues";
export const OP_GET_CONTENTION = "queues.get_contention";
export const OP_RETRY_ATTEMPT = "queues.retry_attempt";
export const OP_VALIDATION_FAILURE = "queues.validation_failure";
