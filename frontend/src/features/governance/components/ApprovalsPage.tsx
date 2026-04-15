/**
 * ApprovalsPage — list approvals filterable by status and request type.
 *
 * Purpose:
 *   Render the governance approvals page at /approvals. Fetches the approval
 *   list via TanStack Query and supports client-side filtering by status
 *   and request type without full page reload (AC-8).
 *
 * Responsibilities:
 *   - Fetch approval list via governanceApi.listApprovals().
 *   - Filter approvals by status (all/pending/approved/rejected).
 *   - Render each approval as an expandable detail card.
 *   - Handle approve/reject actions with mutation + refetch.
 *   - Show loading, error, and empty states.
 *   - Wire SoD guard on each approval detail.
 *
 * Does NOT:
 *   - Manage routing (parent provides via React Router).
 *   - Handle authentication (AuthGuard wraps this in router).
 *
 * Dependencies:
 *   - TanStack Query for data fetching.
 *   - governanceApi for HTTP calls.
 *   - ApprovalDetail for individual approval rendering.
 *   - useAuth for current user context.
 *
 * Example:
 *   <ApprovalsPage />
 */

import { memo, useState, useCallback, useMemo, useId, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { governanceApi } from "../api";
import { governanceLogger } from "../logger";
import type { GovernanceStatus } from "@/types/governance";
import { STATUS_FILTER_OPTIONS } from "../constants";
import { GovernanceAuthError, GovernanceSoDError, GovernanceValidationError } from "../errors";
import { useAuth } from "@/auth/useAuth";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { ApprovalDetail } from "./ApprovalDetail";
import { ApprovalCardList } from "./ApprovalCardList";
import { MobileApprovalDetail } from "./MobileApprovalDetail";

/**
 * Governance approvals list page with status filtering.
 *
 * Filters are applied client-side for instant feedback (AC-8: "filters by
 * status without full page reload").
 */
export const ApprovalsPage = memo(function ApprovalsPage() {
  const correlationId = useId();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();

  const [statusFilter, setStatusFilter] = useState<GovernanceStatus | "all">("all");
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(null);

  // Log page lifecycle.
  useEffect(() => {
    governanceLogger.pageMount("ApprovalsPage", correlationId);
    return () => governanceLogger.pageUnmount("ApprovalsPage", correlationId);
  }, [correlationId]);

  // Fetch approvals.
  const {
    data: approvals,
    isLoading,
    error: fetchError,
    refetch,
  } = useQuery({
    queryKey: ["governance", "approvals"],
    queryFn: ({ signal }) => governanceApi.listApprovals(correlationId, signal),
  });

  // Approve mutation.
  const approveMutation = useMutation({
    mutationFn: (approvalId: string) => governanceApi.approveRequest(approvalId, correlationId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ["governance", "approvals"] });
    },
    onError: (err) => {
      const msg =
        err instanceof GovernanceSoDError
          ? "You cannot approve your own request."
          : err instanceof GovernanceAuthError
            ? "You do not have permission to approve requests."
            : err instanceof GovernanceValidationError
              ? "The server returned an invalid response. Please contact support."
              : err instanceof Error
                ? err.message
                : "An unexpected error occurred.";
      setActionError(msg);
    },
  });

  // Reject mutation.
  const rejectMutation = useMutation({
    mutationFn: ({ approvalId, rationale }: { approvalId: string; rationale: string }) =>
      governanceApi.rejectRequest(approvalId, rationale, correlationId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: ["governance", "approvals"] });
    },
    onError: (err) => {
      const msg =
        err instanceof GovernanceSoDError
          ? "You cannot reject your own request."
          : err instanceof GovernanceAuthError
            ? "You do not have permission to reject requests."
            : err instanceof GovernanceValidationError
              ? "The server returned an invalid response. Please contact support."
              : err instanceof Error
                ? err.message
                : "An unexpected error occurred.";
      setActionError(msg);
    },
  });

  const handleApprove = useCallback(
    (approvalId: string) => {
      approveMutation.mutate(approvalId);
    },
    [approveMutation],
  );

  const handleReject = useCallback(
    (approvalId: string, rationale: string) => {
      rejectMutation.mutate({ approvalId, rationale });
    },
    [rejectMutation],
  );

  // Client-side filtering (AC-8).
  const filteredApprovals = useMemo(() => {
    if (!approvals) return [];
    if (statusFilter === "all") return approvals;
    return approvals.filter((a) => a.status === statusFilter);
  }, [approvals, statusFilter]);

  const isActioning = approveMutation.isPending || rejectMutation.isPending;

  // Loading state.
  if (isLoading) {
    return (
      <div
        data-testid="approvals-loading"
        role="status"
        className="flex items-center justify-center py-12"
      >
        <p className="text-sm text-slate-500">Loading approvals...</p>
      </div>
    );
  }

  // Error state.
  if (fetchError) {
    return (
      <div
        data-testid="approvals-error"
        role="alert"
        className="mx-auto max-w-2xl rounded-lg border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700"
      >
        <p className="font-medium">Failed to load approvals</p>
        <p className="mt-1">
          {fetchError instanceof Error ? fetchError.message : "An unexpected error occurred."}
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-3 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  // Mobile layout: ApprovalCardList + MobileApprovalDetail in BottomSheet
  if (isMobile) {
    return (
      <div data-testid="approvals-page-mobile" className="space-y-4 px-4 py-4">
        <h1 className="text-xl font-semibold text-slate-900">Governance Approvals</h1>

        {/* Action error banner */}
        {actionError && (
          <div
            data-testid="approvals-action-error"
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
          >
            {actionError}
          </div>
        )}

        {/* Mobile approval card list */}
        <ApprovalCardList
          approvals={approvals ?? []}
          onApprovalClick={setSelectedApprovalId}
          isLoading={isLoading}
        />

        {/* Mobile approval detail in BottomSheet */}
        <MobileApprovalDetail
          approvalId={selectedApprovalId}
          isOpen={selectedApprovalId !== null}
          onClose={() => setSelectedApprovalId(null)}
          currentUserId={user?.userId ?? ""}
          onApprove={handleApprove}
          onReject={handleReject}
          isActioning={isActioning}
        />
      </div>
    );
  }

  // Desktop layout: Original expandable cards
  return (
    <div data-testid="approvals-page-desktop" className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Governance Approvals</h1>

        {/* Status filter (AC-8: filters without full page reload) */}
        <select
          data-testid="approvals-status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as GovernanceStatus | "all")}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          aria-label="Filter approvals by status"
        >
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Action error banner */}
      {actionError && (
        <div
          data-testid="approvals-action-error"
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {actionError}
        </div>
      )}

      {/* Approval list */}
      {filteredApprovals.length === 0 ? (
        <div data-testid="approvals-empty" className="py-12 text-center text-sm text-slate-500">
          {statusFilter === "all"
            ? "No approval requests found."
            : `No ${statusFilter} approvals found.`}
        </div>
      ) : (
        <div className="space-y-4">
          {filteredApprovals.map((approval) => (
            <div
              key={approval.id}
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
            >
              <ApprovalDetail
                approval={approval}
                currentUserId={user?.userId ?? ""}
                onApprove={handleApprove}
                onReject={handleReject}
                isActioning={isActioning}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
