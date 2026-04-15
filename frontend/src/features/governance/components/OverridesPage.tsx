/**
 * OverridesPage — list overrides filterable by status and governance gate.
 *
 * Purpose:
 *   Render the governance overrides page at /overrides. Fetches override list
 *   via TanStack Query, supports client-side filtering, and provides the
 *   OverrideRequestForm modal for new requests.
 *
 * Responsibilities:
 *   - Fetch override list via governanceApi.listOverrides().
 *   - Filter by status (all/pending/approved/rejected).
 *   - Filter by override type (all/blocker_waiver/grade_override).
 *   - Render each override as an OverrideViewer card.
 *   - Provide "New Override Request" button opening the form modal.
 *
 * Does NOT:
 *   - Manage routing (parent provides via React Router).
 *   - Handle authentication (AuthGuard wraps this in router).
 *
 * Dependencies:
 *   - TanStack Query for data fetching.
 *   - governanceApi for HTTP calls.
 *   - OverrideViewer for individual override rendering.
 *   - OverrideRequestForm for new override requests.
 *
 * Example:
 *   <OverridesPage />
 */

import { memo, useState, useCallback, useMemo, useId, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { governanceApi } from "../api";
import { governanceLogger } from "../logger";
import type {
  GovernanceStatus,
  OverrideType,
  OverrideRequestForm as OverrideRequestFormType,
} from "@/types/governance";
import { STATUS_FILTER_OPTIONS, OVERRIDE_TYPE_FILTER_OPTIONS } from "../constants";
import { GovernanceAuthError, GovernanceValidationError } from "../errors";
import { OverrideViewer } from "./OverrideViewer";
import { OverrideRequestForm } from "./OverrideRequestForm";

/**
 * Governance overrides list page with status and type filtering.
 */
export const OverridesPage = memo(function OverridesPage() {
  const correlationId = useId();
  const queryClient = useQueryClient();

  const [statusFilter, setStatusFilter] = useState<GovernanceStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<OverrideType | "all">("all");
  const [showRequestForm, setShowRequestForm] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Log page lifecycle.
  useEffect(() => {
    governanceLogger.pageMount("OverridesPage", correlationId);
    return () => governanceLogger.pageUnmount("OverridesPage", correlationId);
  }, [correlationId]);

  // Fetch overrides.
  const {
    data: overrides,
    isLoading,
    error: fetchError,
    refetch,
  } = useQuery({
    queryKey: ["governance", "overrides"],
    queryFn: ({ signal }) => governanceApi.listOverrides(correlationId, signal),
  });

  // Submit override request mutation.
  const requestMutation = useMutation({
    mutationFn: (data: OverrideRequestFormType) =>
      governanceApi.requestOverride(data, correlationId),
    onSuccess: () => {
      setActionError(null);
      setShowRequestForm(false);
      queryClient.invalidateQueries({ queryKey: ["governance", "overrides"] });
    },
    onError: (err) => {
      const msg =
        err instanceof GovernanceAuthError
          ? "You do not have permission to request overrides."
          : err instanceof GovernanceValidationError
            ? "The server returned an invalid response. Please contact support."
            : err instanceof Error
              ? err.message
              : "An unexpected error occurred.";
      setActionError(msg);
    },
  });

  const handleRequestSubmit = useCallback(
    (data: OverrideRequestFormType) => {
      requestMutation.mutate(data);
    },
    [requestMutation],
  );

  // Client-side filtering.
  const filteredOverrides = useMemo(() => {
    if (!overrides) return [];
    return overrides.filter((o) => {
      if (statusFilter !== "all" && o.status !== statusFilter) return false;
      if (typeFilter !== "all" && o.override_type !== typeFilter) return false;
      return true;
    });
  }, [overrides, statusFilter, typeFilter]);

  // Loading state.
  if (isLoading) {
    return (
      <div
        data-testid="overrides-loading"
        role="status"
        className="flex items-center justify-center py-12"
      >
        <p className="text-sm text-slate-500">Loading overrides...</p>
      </div>
    );
  }

  // Error state.
  if (fetchError) {
    return (
      <div
        data-testid="overrides-error"
        role="alert"
        className="mx-auto max-w-2xl rounded-lg border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700"
      >
        <p className="font-medium">Failed to load overrides</p>
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

  return (
    <div data-testid="overrides-page" className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Governance Overrides</h1>

        <button
          type="button"
          onClick={() => setShowRequestForm(true)}
          data-testid="new-override-button"
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1"
        >
          New Override Request
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <select
          data-testid="overrides-status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as GovernanceStatus | "all")}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          aria-label="Filter overrides by status"
        >
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          data-testid="overrides-type-filter"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as OverrideType | "all")}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          aria-label="Filter overrides by type"
        >
          {OVERRIDE_TYPE_FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Action error banner */}
      {actionError && (
        <div
          data-testid="overrides-action-error"
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {actionError}
        </div>
      )}

      {/* Override list */}
      {filteredOverrides.length === 0 ? (
        <div data-testid="overrides-empty" className="py-12 text-center text-sm text-slate-500">
          No overrides found matching the current filters.
        </div>
      ) : (
        <div className="space-y-4">
          {filteredOverrides.map((override) => (
            <div
              key={override.id}
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
            >
              <OverrideViewer override={override} />
            </div>
          ))}
        </div>
      )}

      {/* New override request form modal */}
      <OverrideRequestForm
        isOpen={showRequestForm}
        onClose={() => setShowRequestForm(false)}
        onSubmit={handleRequestSubmit}
        isSubmitting={requestMutation.isPending}
      />
    </div>
  );
});
