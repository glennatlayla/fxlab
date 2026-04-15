/**
 * Governance feature constants — centralized values for statuses, colors, and API config.
 *
 * Purpose:
 *   Single source of truth for governance status styling, labels, filter options,
 *   and API retry parameters.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 *
 * Dependencies:
 *   - None (pure constants).
 */

import type { GovernanceStatus, OverrideType } from "@/types/governance";

// ---------------------------------------------------------------------------
// Status badge styling
// ---------------------------------------------------------------------------

/**
 * Tailwind class sets for governance status badges.
 *
 * pending: yellow (needs attention)
 * approved: green (accepted)
 * rejected: red (declined)
 */
export const STATUS_BADGE_CLASSES: Record<GovernanceStatus, string> = {
  pending: "bg-yellow-100 text-yellow-800 ring-yellow-600/20",
  approved: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  rejected: "bg-red-100 text-red-800 ring-red-600/20",
};

/** Human-readable status labels. */
export const STATUS_LABELS: Record<GovernanceStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
};

// ---------------------------------------------------------------------------
// Override type labels
// ---------------------------------------------------------------------------

/** Human-readable override type labels. */
export const OVERRIDE_TYPE_LABELS: Record<OverrideType, string> = {
  blocker_waiver: "Blocker Waiver",
  grade_override: "Grade Override",
};

// ---------------------------------------------------------------------------
// Filter options
// ---------------------------------------------------------------------------

/** Available status filter options for approval and override lists. */
export const STATUS_FILTER_OPTIONS = [
  { value: "all", label: "All Statuses" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
] as const;

/** Available request type filter options for the approvals list. */
export const REQUEST_TYPE_FILTER_OPTIONS = [
  { value: "all", label: "All Types" },
  { value: "promotion", label: "Promotion" },
  { value: "override", label: "Override" },
] as const;

/** Available override type filter options. */
export const OVERRIDE_TYPE_FILTER_OPTIONS = [
  { value: "all", label: "All Types" },
  { value: "blocker_waiver", label: "Blocker Waiver" },
  { value: "grade_override", label: "Grade Override" },
] as const;

// ---------------------------------------------------------------------------
// API & retry
// ---------------------------------------------------------------------------

/** Maximum retry attempts for governance API calls. */
export const GOVERNANCE_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const GOVERNANCE_API_RETRY_BASE_DELAY_MS = 1000;

/** Jitter factor for retry backoff. */
export const GOVERNANCE_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Form validation
// ---------------------------------------------------------------------------

/** Minimum rationale length for approval rejections. */
export const APPROVAL_RATIONALE_MIN_LENGTH = 10;

/** Minimum rationale length for override requests (SOC 2). */
export const OVERRIDE_RATIONALE_MIN_LENGTH = 20;

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_LIST_APPROVALS = "governance.list_approvals";
export const OP_APPROVE_REQUEST = "governance.approve_request";
export const OP_REJECT_REQUEST = "governance.reject_request";
export const OP_LIST_OVERRIDES = "governance.list_overrides";
export const OP_GET_OVERRIDE = "governance.get_override";
export const OP_REQUEST_OVERRIDE = "governance.request_override";
export const OP_LIST_PROMOTIONS = "governance.list_promotions";
export const OP_RENDER_APPROVALS_PAGE = "governance.render_approvals_page";
export const OP_RENDER_OVERRIDES_PAGE = "governance.render_overrides_page";
