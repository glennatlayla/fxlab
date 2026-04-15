/**
 * ApprovalDetail — display a single approval request with approve/reject controls.
 *
 * Purpose:
 *   Render the full detail of an approval request including submitter, timestamps,
 *   status, and decision rationale. Approve/reject actions are gated by the
 *   SeparationGuard component to enforce SoD.
 *
 * Responsibilities:
 *   - Display approval metadata (submitter, created_at, status, decision_reason).
 *   - Render approve/reject buttons for pending requests (gated by SeparationGuard).
 *   - Open ConfirmationModal with rationale input for rejection.
 *   - Show read-only state for decided approvals (approved/rejected).
 *
 * Does NOT:
 *   - Fetch approval data (parent provides it).
 *   - Execute API calls (parent provides callbacks).
 *
 * Dependencies:
 *   - SeparationGuard for SoD enforcement.
 *   - ConfirmationModal for approve/reject confirmation.
 *
 * Example:
 *   <ApprovalDetail
 *     approval={approval}
 *     currentUserId={user.id}
 *     onApprove={handleApprove}
 *     onReject={handleReject}
 *   />
 */

import { memo, useState, useCallback } from "react";
import type { ApprovalDetail as ApprovalDetailType } from "@/types/governance";
import { STATUS_BADGE_CLASSES, STATUS_LABELS, APPROVAL_RATIONALE_MIN_LENGTH } from "../constants";
import { SeparationGuard } from "./SeparationGuard";
import { ConfirmationModal } from "./ConfirmationModal";

export interface ApprovalDetailProps {
  /** The approval request to display. */
  approval: ApprovalDetailType;
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
 * Render approval detail with conditional action controls.
 *
 * For pending approvals where the current user is not the submitter,
 * renders approve/reject buttons. For decided approvals, renders
 * the decision outcome as read-only.
 */
export const ApprovalDetail = memo(function ApprovalDetail({
  approval,
  currentUserId,
  onApprove,
  onReject,
  isActioning = false,
}: ApprovalDetailProps) {
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectRationale, setRejectRationale] = useState("");

  const isPending = approval.status === "pending";

  const handleApproveConfirm = useCallback(() => {
    onApprove(approval.id);
    setShowApproveModal(false);
  }, [approval.id, onApprove]);

  const handleRejectConfirm = useCallback(() => {
    onReject(approval.id, rejectRationale.trim());
    setShowRejectModal(false);
    setRejectRationale("");
  }, [approval.id, rejectRationale, onReject]);

  const handleRejectCancel = useCallback(() => {
    setShowRejectModal(false);
    setRejectRationale("");
  }, []);

  const isRejectValid = rejectRationale.trim().length >= APPROVAL_RATIONALE_MIN_LENGTH;

  return (
    <div data-testid={`approval-detail-${approval.id}`} className="space-y-4">
      {/* Status badge */}
      <div className="flex items-center gap-3">
        <span
          data-testid="approval-status-badge"
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_BADGE_CLASSES[approval.status]}`}
        >
          {STATUS_LABELS[approval.status]}
        </span>
        <span className="text-sm text-slate-500">
          {new Date(approval.created_at).toLocaleString()}
        </span>
      </div>

      {/* Metadata */}
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
        <dt className="font-medium text-slate-600">Submitted by</dt>
        <dd data-testid="approval-submitter" className="text-slate-900">
          {approval.requested_by}
        </dd>

        {approval.reviewer_id && (
          <>
            <dt className="font-medium text-slate-600">Reviewed by</dt>
            <dd data-testid="approval-reviewer" className="text-slate-900">
              {approval.reviewer_id}
            </dd>
          </>
        )}

        {approval.decided_at && (
          <>
            <dt className="font-medium text-slate-600">Decided at</dt>
            <dd className="text-slate-900">{new Date(approval.decided_at).toLocaleString()}</dd>
          </>
        )}
      </dl>

      {/* Decision rationale (for decided approvals) */}
      {approval.decision_reason && (
        <div
          data-testid="approval-decision-reason"
          className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
        >
          <p className="font-medium text-slate-600">Decision Rationale</p>
          <p className="mt-1">{approval.decision_reason}</p>
        </div>
      )}

      {/* Action controls (only for pending approvals) */}
      {isPending && (
        <SeparationGuard currentUserId={currentUserId} submitterId={approval.requested_by}>
          <div data-testid="approval-actions" className="flex items-center gap-3">
            <button
              type="button"
              disabled={isActioning}
              onClick={() => setShowApproveModal(true)}
              data-testid="approve-button"
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Approve
            </button>
            <button
              type="button"
              disabled={isActioning}
              onClick={() => setShowRejectModal(true)}
              data-testid="reject-button"
              className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </SeparationGuard>
      )}

      {/* Approve confirmation modal */}
      <ConfirmationModal
        isOpen={showApproveModal}
        onClose={() => setShowApproveModal(false)}
        title="Approve Request"
      >
        <p className="text-sm text-slate-600">
          Are you sure you want to approve this request? This action cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-3">
          <button
            type="button"
            onClick={() => setShowApproveModal(false)}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApproveConfirm}
            disabled={isActioning}
            data-testid="confirm-approve-button"
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Confirm Approve
          </button>
        </div>
      </ConfirmationModal>

      {/* Reject confirmation modal with rationale */}
      <ConfirmationModal
        isOpen={showRejectModal}
        onClose={handleRejectCancel}
        title="Reject Request"
      >
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Provide a rationale for rejection. This becomes the permanent audit record.
          </p>
          <textarea
            data-testid="reject-rationale-input"
            value={rejectRationale}
            onChange={(e) => setRejectRationale(e.target.value)}
            disabled={isActioning}
            placeholder="Rejection rationale (minimum 10 characters)..."
            rows={3}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 disabled:opacity-50"
          />
          <p className="text-xs text-slate-500">
            {rejectRationale.trim().length}/{APPROVAL_RATIONALE_MIN_LENGTH} characters minimum
          </p>
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={handleRejectCancel}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleRejectConfirm}
              disabled={!isRejectValid || isActioning}
              data-testid="confirm-reject-button"
              className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Confirm Reject
            </button>
          </div>
        </div>
      </ConfirmationModal>
    </div>
  );
});
