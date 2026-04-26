/**
 * AlertsPage — Alert feed screen with filtering, pagination, and detail view.
 *
 * Purpose:
 *   Display a mobile-optimized feed of system and trading alerts.
 *   Support filtering by severity, pagination via infinite scroll,
 *   and detailed alert view in a BottomSheet.
 *
 * Responsibilities:
 *   - Fetch alerts via useInfiniteQuery with react-query.
 *   - Manage filter state and filtered alert display.
 *   - Handle alert detail view (open/close BottomSheet).
 *   - Support acknowledge action via API.
 *   - Auto-refresh alerts every 15 seconds.
 *   - Show loading, error, and empty states.
 *
 * Does NOT:
 *   - Contain API logic (delegated to alertsApi).
 *   - Manage global alert state.
 *   - Send notifications directly.
 *
 * Dependencies:
 *   - React, useState, useEffect, useCallback
 *   - react-query: useInfiniteQuery, useQueryClient
 *   - AlertCard, AlertDetail components
 *   - BottomSheet component
 *   - lucide-react: RefreshCw icon
 *   - alertsApi from ./api
 *   - Alert, AlertFilterType from ./types
 *
 * Error conditions:
 *   - Network failures: shown with error message and retry button.
 *   - 404 deployment not found: shown as error.
 *   - Empty alert list: shown as empty state with icon.
 *
 * Example:
 *   <AlertsPage deploymentId="deploy-001" />
 */

import React, { useState, useEffect, useCallback } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import { BottomSheet } from "@/components/mobile/BottomSheet";
import { alertsApi } from "./api";
import { AlertCard } from "./components/AlertCard";
import { AlertDetail } from "./components/AlertDetail";
import type { Alert, AlertFilterType, AlertListResponse } from "./types";

export interface AlertsPageProps {
  /** Deployment ID to fetch alerts for. */
  deploymentId: string;
}

/**
 * Fetch alerts for a deployment with optional filtering.
 *
 * Uses useInfiniteQuery to support pagination via infinite scroll.
 * Auto-refetches every 15 seconds when page is visible.
 */
function useAlertsInfiniteQuery(deploymentId: string) {
  const queryClient = useQueryClient();

  // Set up auto-refresh interval (every 15 seconds when visible)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        queryClient.invalidateQueries({ queryKey: ["alerts", deploymentId] });
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    const interval = setInterval(() => {
      if (document.visibilityState === "visible") {
        queryClient.invalidateQueries({ queryKey: ["alerts", deploymentId] });
      }
    }, 15000);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      clearInterval(interval);
    };
  }, [deploymentId, queryClient]);

  return useInfiniteQuery({
    queryKey: ["alerts", deploymentId],
    queryFn: async ({ pageParam = undefined }): Promise<AlertListResponse> => {
      return alertsApi.listAlerts({
        deploymentId,
        cursor: pageParam as string | undefined,
      });
    },
    getNextPageParam: (lastPage: AlertListResponse) => lastPage.next_cursor,
    staleTime: 30000, // 30 seconds
    retry: 2,
    initialPageParam: undefined,
  });
}

/**
 * AlertsPage component.
 *
 * Main alert feed view with filter chips, alert card list, and
 * detail view modal.
 *
 * Example:
 *   <AlertsPage deploymentId="deploy-001" />
 */
export function AlertsPage({ deploymentId }: AlertsPageProps): React.ReactElement {
  // State management
  const [selectedFilter, setSelectedFilter] = useState<AlertFilterType>("all");
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);

  // Data fetching
  const { data, isLoading, isError, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useAlertsInfiniteQuery(deploymentId);

  // Flatten paginated alerts
  const allAlerts = data?.pages.flatMap((page: AlertListResponse) => page.alerts) ?? [];

  // Apply severity filter
  const filteredAlerts =
    selectedFilter === "all"
      ? allAlerts
      : allAlerts.filter((alert) => alert.severity === selectedFilter);

  // Count unacknowledged alerts
  const unacknowledgedCount = allAlerts.filter((alert) => !alert.acknowledged).length;

  // Handle alert card click
  const handleAlertClick = useCallback((alert: Alert) => {
    setSelectedAlert(alert);
    setIsDetailOpen(true);
  }, []);

  // Handle acknowledge
  const handleAcknowledge = useCallback(
    async (alertId: string) => {
      try {
        await alertsApi.acknowledgeAlert(alertId);

        // Optimistically update local state
        if (selectedAlert && selectedAlert.id === alertId) {
          setSelectedAlert({
            ...selectedAlert,
            acknowledged: true,
            acknowledged_at: new Date().toISOString(),
          });
        }

        // Close detail view
        setIsDetailOpen(false);
      } catch (err) {
        console.error("Failed to acknowledge alert:", err);
      }
    },
    [selectedAlert],
  );

  // Handle detail close
  const handleCloseDetail = useCallback(() => {
    setIsDetailOpen(false);
  }, []);

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Alerts</h1>
          <p className="text-sm text-surface-500">Loading alerts...</p>
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              data-testid="skeleton"
              className="h-24 animate-pulse rounded-lg border border-surface-200 bg-surface-50"
            />
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Alerts</h1>
          <p className="text-sm text-surface-500">Failed to load alerts</p>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-medium text-red-900">
            Error: {error instanceof Error ? error.message : "Unknown error"}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-red-600 px-4 py-2 font-medium text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Alerts</h1>
          {unacknowledgedCount > 0 && (
            <p className="mt-1 text-sm text-surface-600">{unacknowledgedCount} unacknowledged</p>
          )}
        </div>
      </div>

      {/* Filter Chips */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {(["all", "critical", "warning", "info"] as const).map((filter) => (
          <button
            key={filter}
            onClick={() => setSelectedFilter(filter)}
            className={clsx(
              "flex-shrink-0 rounded-full px-4 py-2 font-medium capitalize transition-colors",
              selectedFilter === filter
                ? "bg-blue-600 text-white"
                : "bg-surface-100 text-surface-700 hover:bg-surface-200",
            )}
          >
            {filter}
            {filter !== "all" && (
              <span className="ml-1">
                ({allAlerts.filter((a) => a.severity === filter).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Alert List */}
      {filteredAlerts.length === 0 ? (
        <div className="rounded-lg border border-surface-200 bg-surface-50 py-12 text-center">
          <p className="text-surface-400">No alerts</p>
          <p className="mt-1 text-xs text-surface-500">
            {selectedFilter === "all"
              ? "No alerts found for this deployment"
              : `No ${selectedFilter} severity alerts`}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filteredAlerts.map((alert) => (
            <AlertCard key={alert.id} alert={alert} onClick={handleAlertClick} />
          ))}

          {/* Load More Button (for infinite scroll) */}
          {hasNextPage && (
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="w-full rounded-lg border border-surface-200 bg-white px-4 py-3 font-medium text-surface-700 transition-colors hover:bg-surface-50 disabled:opacity-50"
            >
              {isFetchingNextPage ? (
                <>
                  <RefreshCw className="mr-2 inline-block h-4 w-4 animate-spin" />
                  Loading more...
                </>
              ) : (
                "Load More Alerts"
              )}
            </button>
          )}
        </div>
      )}

      {/* Detail BottomSheet */}
      {selectedAlert && (
        <BottomSheet isOpen={isDetailOpen} onClose={handleCloseDetail} title={selectedAlert.title}>
          <AlertDetail alert={selectedAlert} onAcknowledge={handleAcknowledge} />
        </BottomSheet>
      )}
    </div>
  );
}
