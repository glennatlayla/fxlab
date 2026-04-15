/**
 * ApprovalCardList — scrollable mobile list of approval cards with status filtering.
 *
 * Purpose:
 *   Render a vertical stack of ApprovalCards with client-side status filtering.
 *   Supports filter chips (All, Pending, Approved, Rejected) and displays
 *   empty state and loading skeleton.
 *
 * Responsibilities:
 *   - Render filter chips for status filtering.
 *   - Filter approvals by selected status.
 *   - Render each approval as an ApprovalCard.
 *   - Show empty state when no results match filter.
 *   - Show loading skeleton when isLoading is true.
 *   - Forward card clicks to onApprovalClick callback.
 *
 * Does NOT:
 *   - Fetch approval data (parent provides it).
 *   - Execute API calls.
 *
 * Dependencies:
 *   - ApprovalCard component.
 *   - ApprovalDetail type from @/types/governance.
 *   - STATUS_FILTER_OPTIONS from ../constants.
 *   - clsx for conditional styling.
 *
 * Example:
 *   <ApprovalCardList
 *     approvals={approvals}
 *     onApprovalClick={(id) => setSelectedId(id)}
 *     isLoading={isLoading}
 *   />
 */

import { memo, useState, useMemo } from "react";
import type { ApprovalDetail, GovernanceStatus } from "@/types/governance";
import { STATUS_FILTER_OPTIONS } from "../constants";
import { ApprovalCard } from "./ApprovalCard";
import clsx from "clsx";

export interface ApprovalCardListProps {
  /** Array of approvals to display. */
  approvals: ApprovalDetail[];
  /** Callback when an approval card is clicked, receives approval ID. */
  onApprovalClick: (approvalId: string) => void;
  /** Whether data is currently loading. */
  isLoading?: boolean;
}

/**
 * ApprovalCardList component.
 *
 * Renders a list of ApprovalCards with status filter chips at the top.
 * Supports All, Pending, Approved, and Rejected filters. Shows empty
 * state when no approvals match the selected filter. Shows loading skeleton
 * when isLoading is true.
 *
 * Example:
 *   <ApprovalCardList
 *     approvals={approvals}
 *     onApprovalClick={(id) => openDetail(id)}
 *     isLoading={false}
 *   />
 */
export const ApprovalCardList = memo(function ApprovalCardList({
  approvals,
  onApprovalClick,
  isLoading = false,
}: ApprovalCardListProps) {
  const [statusFilter, setStatusFilter] = useState<GovernanceStatus | "all">("all");

  // Client-side filtering
  const filteredApprovals = useMemo(() => {
    if (statusFilter === "all") {
      return approvals;
    }
    return approvals.filter((a) => a.status === statusFilter);
  }, [approvals, statusFilter]);

  // Loading state
  if (isLoading) {
    return (
      <div data-testid="approval-card-list-loading" className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 rounded-lg border border-slate-200 bg-slate-100 animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div data-testid="approval-card-list" className="space-y-4">
      {/* Filter chips */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {STATUS_FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => setStatusFilter(opt.value as GovernanceStatus | "all")}
            className={clsx(
              "whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
              statusFilter === opt.value
                ? "bg-brand-500 text-white"
                : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
            )}
            aria-pressed={statusFilter === opt.value}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Approval cards or empty state */}
      {filteredApprovals.length === 0 ? (
        <div
          data-testid="approval-card-list-empty"
          className="py-8 text-center text-sm text-slate-500"
        >
          <p>
            {statusFilter === "all"
              ? "No approval requests found."
              : `No ${statusFilter} approvals found.`}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredApprovals.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onClick={onApprovalClick}
            />
          ))}
        </div>
      )}
    </div>
  );
});
