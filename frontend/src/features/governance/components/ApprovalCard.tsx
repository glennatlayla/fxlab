/**
 * ApprovalCard — compact mobile card for a single approval request.
 *
 * Purpose:
 *   Render a single approval in mobile list view. Shows status badge, submitter,
 *   timestamp, entity type/ID, and optional decision reason. Entire card is
 *   clickable to open detail view.
 *
 * Responsibilities:
 *   - Display status badge with color-coded styling (pending/approved/rejected).
 *   - Show submitter name/ID, timestamp, and entity information.
 *   - Show decision reason for decided approvals.
 *   - Fire onClick callback when card is tapped.
 *   - Render chevron icon indicating tappability.
 *
 * Does NOT:
 *   - Fetch approval data (parent provides it).
 *   - Execute API calls.
 *   - Manage modal or detail view state (parent handles that).
 *
 * Dependencies:
 *   - ApprovalDetail type from @/types/governance.
 *   - STATUS_BADGE_CLASSES, STATUS_LABELS from ../constants.
 *   - lucide-react (ChevronRight icon).
 *   - clsx for conditional styling.
 *
 * Example:
 *   <ApprovalCard
 *     approval={approval}
 *     onClick={(id) => setSelectedApprovalId(id)}
 *   />
 */

import { memo } from "react";
import { ChevronRight } from "lucide-react";
import type { ApprovalDetail } from "@/types/governance";
import { STATUS_BADGE_CLASSES, STATUS_LABELS } from "../constants";
import clsx from "clsx";

export interface ApprovalCardProps {
  /** The approval request to display. */
  approval: ApprovalDetail;
  /** Callback when the card is clicked, receives approval ID. */
  onClick: (approvalId: string) => void;
}

/**
 * ApprovalCard component.
 *
 * Renders a full-width, rounded card with approval metadata. Status badge
 * is color-coded: pending (amber), approved (green), rejected (red).
 * Entire card is clickable.
 *
 * Example:
 *   <ApprovalCard
 *     approval={approval}
 *     onClick={(id) => setSelectedId(id)}
 *   />
 */
export const ApprovalCard = memo(function ApprovalCard({ approval, onClick }: ApprovalCardProps) {
  const handleClick = () => {
    onClick(approval.id);
  };

  return (
    <button
      type="button"
      data-testid="approval-card"
      onClick={handleClick}
      className="w-full rounded-lg border border-slate-200 bg-white p-3 text-left shadow-sm transition-all hover:border-slate-300 hover:shadow-md active:shadow-none"
    >
      {/* Top row: Status badge + timestamp */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <span
          data-testid="approval-card-status-badge"
          className={clsx(
            "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
            STATUS_BADGE_CLASSES[approval.status],
          )}
        >
          {STATUS_LABELS[approval.status]}
        </span>
        <span data-testid="approval-card-timestamp" className="text-xs text-slate-500">
          {new Date(approval.created_at).toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {/* Middle row: Submitter + entity type/ID */}
      <div className="mb-2 space-y-1">
        <p data-testid="approval-card-submitter" className="text-sm font-medium text-slate-900">
          {approval.requested_by}
        </p>
        {approval.entity_type && approval.entity_id && (
          <p data-testid="approval-card-entity" className="text-xs text-slate-600">
            {approval.entity_type} — {approval.entity_id}
          </p>
        )}
      </div>

      {/* Decision reason if available */}
      {approval.decision_reason && (
        <div className="mb-2 rounded bg-slate-50 px-2 py-1">
          <p
            data-testid="approval-card-decision-reason"
            className="line-clamp-2 text-xs text-slate-700"
          >
            {approval.decision_reason}
          </p>
        </div>
      )}

      {/* Chevron on the right to indicate tappability */}
      <div className="flex justify-end">
        <ChevronRight data-testid="approval-card-chevron" className="h-4 w-4 text-slate-400" />
      </div>
    </button>
  );
});
