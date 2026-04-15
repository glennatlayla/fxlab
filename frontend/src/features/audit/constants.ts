/**
 * Audit feature constants — centralized values for action labels and API config.
 *
 * Purpose:
 *   Single source of truth for audit action labels, page size settings,
 *   and API retry parameters used across the Audit Explorer feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 */

// ---------------------------------------------------------------------------
// Action type labels
// ---------------------------------------------------------------------------

/**
 * Human-readable labels for audit action types.
 *
 * Maps backend action identifiers (e.g., "strategy.created") to user-facing
 * labels displayed in the audit explorer UI.
 */
export const ACTION_TYPE_LABELS: Record<string, string> = {
  // Strategy actions
  "strategy.created": "Strategy Created",
  "strategy.updated": "Strategy Updated",
  "strategy.deleted": "Strategy Deleted",
  "strategy.activated": "Strategy Activated",
  "strategy.deactivated": "Strategy Deactivated",
  "strategy.paused": "Strategy Paused",
  "strategy.resumed": "Strategy Resumed",
  "strategy.backtest_run": "Backtest Run",

  // Promotion actions
  "strategy.promotion_requested": "Promotion Requested",
  approve_promotion: "Promotion Approved",
  reject_promotion: "Promotion Rejected",

  // Override actions
  create_override: "Override Created",
  update_override: "Override Updated",
  delete_override: "Override Deleted",

  // Feed actions
  "feed.registered": "Feed Registered",
  "feed.unregistered": "Feed Unregistered",
  "feed.config_changed": "Feed Config Changed",
  "feed.health_degraded": "Feed Degraded",
  "feed.health_restored": "Feed Restored",

  // User actions
  "user.login": "User Login",
  "user.logout": "User Logout",
  "user.profile_updated": "Profile Updated",

  // Admin/governance actions
  role_assigned: "Role Assigned",
  role_revoked: "Role Revoked",
  permission_granted: "Permission Granted",
  permission_revoked: "Permission Revoked",
};

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/** Default page size for the audit event list. */
export const AUDIT_DEFAULT_PAGE_SIZE = 20;

/** Maximum page size accepted by the backend. */
export const AUDIT_MAX_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// API & retry (CLAUDE.md §9)
// ---------------------------------------------------------------------------

/** Maximum retry attempts for audit API GET calls. */
export const AUDIT_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const AUDIT_API_RETRY_BASE_DELAY_MS = 1000;

/** Symmetric jitter factor for retry backoff. */
export const AUDIT_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_LIST_AUDIT = "audit.list_audit";
export const OP_GET_AUDIT_EVENT = "audit.get_audit_event";
export const OP_RETRY_ATTEMPT = "audit.retry_attempt";
export const OP_VALIDATION_FAILURE = "audit.validation_failure";
