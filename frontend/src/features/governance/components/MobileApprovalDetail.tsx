/**
 * MobileApprovalDetail — mobile-optimized approval detail in a BottomSheet.
 *
 * Purpose:
 *   Render approval detail in a BottomSheet overlay, optimized for mobile screens.
 *   Fetches approval detail by ID, displays metadata, and provides approve/reject
 *   actions via SlideToConfirm components.
 *
 * Responsibilities:
 *   - Fetch approval detail via governanceApi.getApprovalDetail() with signal support.
 *   - Display approval metadata (submitter, timestamps, status).
 *   - Render SlideToConfirm for approve action (variant="default").
 *   - Render SlideToConfirm for reject action (variant="danger").
 *   - Show loading, error, and success states.
 *   - Manage reject rationale input and validation.
 *   - Enforce SoD (separation of duties) via SeparationGuard.
 *   - Call parent callbacks (onApprove, onReject) with appropriate payloads.
 *
 * Does NOT:
 *   - Execute mutations (parent handles approve/reject API calls).
 *   - Manage bottom sheet visibility (parent manages via isOpen prop).
 *
 * Dependencies:
 *   - BottomSheet component for modal container.
 *   - SlideToConfirm for gesture-based action confirmation.
 *   - SeparationGuard for SoD enforcement.
 *   - TanStack Query (useQuery) for data fetching.
 *   - governanceApi.getApprovalDetail for API calls.
 *   - ApprovalDetail type from @/types/governance.
 *   - APPROVAL_RATIONALE_MIN_LENGTH constant.
 *   - clsx for conditional styling.
 *
 * Example:
 *   <MobileApprovalDetail
 *     approvalId="approval-1"
 *     isOpen={isOpen}
 *     onClose={() => setIsOpen(false)}
 *     currentUserId={user.id}
 *     onApprove={(id) => approveApproval(id)}
 *     onReject={(id, rationale) => rejectApproval(id, rationale)}
 *     isActioning={isApproving || isRejecting}
 *   />
 */

import { memo, useState, useCallback, useId, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { governanceApi } from "../api";
import { BottomSheet } from "@/components/mobile/BottomSheet";
import { SlideToConfirm } from "@/components/mobile/SlideToConfirm";
import { SeparationGuard } from "./SeparationGuard";
import { STATUS_BADGE_CLASSES, STATUS_LABELS, APPROVAL_RATIONALE_MIN_LENGTH } from "../constants";
import clsx from "clsx";

export interface MobileApprovalDetailProps {
  /** The approval ID to fetch and display. */
  approvalId: string | null;
  /** Whether the bottom sheet is open. */
  isOpen: boolean;
  /** Callback when the sheet should close. */
  onClose: () => void;
  /** ULID of the currently authenticated user. */
  currentUserId: string;
  /** Callback to approve the request. */
  onApprove: (approvalId: string) => void;
  /** Callback to reject the request with rationale. */
  onReject: (approvalId: string, rationale: string) => void;
  /** Whether an action is currently in progress. */
  isActioning?: boolean;
}

/**
 * MobileApprovalDetail component.
 *
 * Renders an approval detail in a BottomSheet with approve/reject actions.
 * When approvalId is provided and isOpen is true, fetches and displays the
 * approval with interactive confirmation controls. For pending approvals,
 * renders SlideToConfirm gestures. For decided approvals, shows read-only
 * decision outcome.
 *
 * Example:
 *   <MobileApprovalDetail
 *     approvalId={selectedId}
 *     isOpen={isDetailOpen}
 *     onClose={() => setIsDetailOpen(false)}
 *     currentUserId="user-123"
 *     onApprove={handleApprove}
 *     onReject={handleReject}
 *     isActioning={isActioning}
 *   />
 */
export const MobileApprovalDetail = memo(function MobileApprovalDetail({
  approvalId,
  isOpen,
  onClose,
  currentUserId,
  onApprove,
  onReject,
  isActioning = false,
}: MobileApprovalDetailProps) {
  const correlationId = useId();
  const [rejectRationale, setRejectRationale] = useState("");
  const [showRejectInput, setShowRejectInput] = useState(false);

  // Log lifecycle (optional - can be enhanced with custom logger method if needed)
  useEffect(() => {
    if (isOpen && approvalId) {
      // eslint-disable-next-line no-console
      console.debug("[MobileApprovalDetail] opened", { approvalId, correlationId });
    }
  }, [isOpen, approvalId, correlationId]);

  // Fetch approval detail
  const {
    data: approval,
    isLoading,
    error: fetchError,
    refetch,
  } = useQuery({
    queryKey: ["governance", "approvals", approvalId],
    queryFn: ({ signal }) => {
      if (!approvalId) throw new Error("No approval ID provided");
      return governanceApi.getApprovalDetail(approvalId, correlationId, signal);
    },
    enabled: isOpen && !!approvalId,
    staleTime: 30000,
  });

  const handleApprove = useCallback(() => {
    if (!approvalId) return;
    onApprove(approvalId);
  }, [approvalId, onApprove]);

  const handleRejectConfirm = useCallback(() => {
    if (!approvalId) return;
    const trimmedRationale = rejectRationale.trim();
    if (trimmedRationale.length < APPROVAL_RATIONALE_MIN_LENGTH) {
      return; // Should not happen due to disabled state, but be safe
    }
    onReject(approvalId, trimmedRationale);
    // Reset state after action
    setRejectRationale("");
    setShowRejectInput(false);
  }, [approvalId, rejectRationale, onReject]);

  const isPending = approval?.status === "pending";
  const isRejectValid = rejectRationale.trim().length >= APPROVAL_RATIONALE_MIN_LENGTH;

  // Render content based on state
  let content: React.ReactNode;

  if (isLoading) {
    content = (
      <div data-testid="mobile-approval-detail-loading" className="py-6 text-center">
        <p className="text-sm text-slate-500">Loading approval...</p>
      </div>
    );
  } else if (fetchError) {
    content = (
      <div data-testid="mobile-approval-detail-error" className="space-y-3">
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <p className="font-medium">Failed to load approval</p>
          <p className="mt-1">
            {fetchError instanceof Error ? fetchError.message : "An unexpected error occurred."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="w-full rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  } else if (!approval) {
    content = (
      <div className="py-6 text-center text-sm text-slate-500">
        <p>Approval not found</p>
      </div>
    );
  } else {
    content = (
      <div className="space-y-4">
        {/* Status badge */}
        <div className="flex items-center gap-2">
          <span
            className={clsx(
              "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
              STATUS_BADGE_CLASSES[approval.status],
            )}
          >
            {STATUS_LABELS[approval.status]}
          </span>
          <span className="text-sm text-slate-500">
            {new Date(approval.created_at).toLocaleString()}
          </span>
        </div>

        {/* Metadata */}
        <div className="space-y-2 text-sm">
          <div>
            <p className="font-medium text-slate-600">Submitted by</p>
            <p className="text-slate-900">{approval.requested_by}</p>
          </div>

          {approval.entity_type && approval.entity_id && (
            <div>
              <p className="font-medium text-slate-600">Entity</p>
              <p className="text-slate-900">
                {approval.entity_type} — {approval.entity_id}
              </p>
            </div>
          )}

          {approval.reviewer_id && (
            <div>
              <p className="font-medium text-slate-600">Reviewed by</p>
              <p className="text-slate-900">{approval.reviewer_id}</p>
            </div>
          )}

          {approval.decided_at && (
            <div>
              <p className="font-medium text-slate-600">Decided at</p>
              <p className="text-slate-900">{new Date(approval.decided_at).toLocaleString()}</p>
            </div>
          )}
        </div>

        {/* Decision reason (for decided approvals) */}
        {approval.decision_reason && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
            <p className="font-medium text-slate-600">Decision Rationale</p>
            <p className="mt-1">{approval.decision_reason}</p>
          </div>
        )}

        {/* Action controls (only for pending approvals where current user is not submitter) */}
        {isPending && (
          <SeparationGuard currentUserId={currentUserId} submitterId={approval.requested_by}>
            <div className="space-y-3 pt-2">
              {/* Approve slide */}
              <SlideToConfirm
                data-testid="mobile-approval-detail-approve-slide"
                label="Slide to approve"
                variant="default"
                onConfirm={handleApprove}
                disabled={isActioning}
              />

              {/* Reject section */}
              <div>
                <button
                  type="button"
                  onClick={() => setShowRejectInput(!showRejectInput)}
                  disabled={isActioning}
                  className="w-full rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  {showRejectInput ? "Hide Reject" : "Show Reject"}
                </button>

                {showRejectInput && (
                  <div className="mt-3 space-y-2">
                    <textarea
                      data-testid="mobile-approval-detail-reject-input"
                      value={rejectRationale}
                      onChange={(e) => setRejectRationale(e.currentTarget.value)}
                      disabled={isActioning}
                      placeholder="Rejection rationale (minimum 10 characters)..."
                      rows={3}
                      className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 disabled:opacity-50"
                    />
                    <p className="text-xs text-slate-500">
                      {rejectRationale.trim().length}/{APPROVAL_RATIONALE_MIN_LENGTH} characters
                      minimum
                    </p>

                    {isRejectValid && (
                      <SlideToConfirm
                        data-testid="mobile-approval-detail-reject-slide"
                        label="Slide to reject"
                        variant="danger"
                        onConfirm={handleRejectConfirm}
                        disabled={isActioning}
                      />
                    )}
                  </div>
                )}
              </div>
            </div>
          </SeparationGuard>
        )}
      </div>
    );
  }

  return (
    <BottomSheet
      isOpen={isOpen}
      onClose={onClose}
      title={approval ? `Approval #${approval.id.slice(0, 8)}` : "Approval"}
      maxHeightVh={80}
    >
      {content}
    </BottomSheet>
  );
});
