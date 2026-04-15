/**
 * PaperTradingOverview — main page for paper trading monitor (FE-14).
 *
 * Purpose:
 *   Display a scrollable list of paper trading deployments with live P&L,
 *   allowing users to monitor and manage multiple paper trading simulations.
 *   Provides filtering by status, detail view for each deployment, and
 *   quick access to create new deployments.
 *
 * Responsibilities:
 *   - Fetch list of paper trading deployments on mount.
 *   - Display deployment cards in a scrollable list.
 *   - Provide filter chips to filter by status (All, Active, Frozen, Stopped).
 *   - Handle card click to open deployment detail in a bottom sheet / modal.
 *   - Auto-refresh deployment list every 5 seconds.
 *   - Show loading skeleton while fetching initial list.
 *   - Render empty state when no deployments exist.
 *   - Provide "New" button to create new deployments.
 *
 * Does NOT:
 *   - Contain presentation logic beyond list management.
 *   - Manage global state (uses React Query for caching).
 *   - Directly manipulate deployment status (DeploymentDetail handles it).
 *
 * Dependencies:
 *   - @tanstack/react-query for data fetching and caching.
 *   - DeploymentCard component.
 *   - DeploymentDetail component (in modal / bottom sheet).
 *   - paperTradingApi.
 *
 * Example:
 *   <Route path="/paper" element={<PaperTradingOverview />} />
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { paperTradingApi } from "../api";
import type { PaperDeploymentStatus } from "../types";
import { DeploymentCard } from "./DeploymentCard";
import { DeploymentDetail } from "./DeploymentDetail";

type FilterStatus = "all" | PaperDeploymentStatus;

/**
 * PaperTradingOverview — main paper trading monitoring page.
 */
export function PaperTradingOverview() {
  const [selectedDeploymentId, setSelectedDeploymentId] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<FilterStatus>("all");
  const [isFreezingUnfreezing, setIsFreezingUnfreezing] = useState(false);

  // Fetch deployments list
  const {
    data: deployments = [],
    isLoading: isLoadingDeployments,
    error: deploymentsError,
  } = useQuery({
    queryKey: ["paper-deployments"],
    queryFn: () => paperTradingApi.listDeployments(),
    refetchInterval: 5000, // Auto-refresh every 5 seconds
  });

  // Fetch selected deployment details
  const {
    data: selectedDeployment,
    isLoading: isLoadingDetail,
    refetch: refetchDetail,
  } = useQuery({
    queryKey: ["paper-deployment", selectedDeploymentId],
    queryFn: () =>
      selectedDeploymentId
        ? paperTradingApi.getDeploymentDetail(selectedDeploymentId)
        : null,
    enabled: selectedDeploymentId !== null,
  });

  // Fetch positions for selected deployment
  const { data: positions = [] } = useQuery({
    queryKey: ["paper-positions", selectedDeploymentId],
    queryFn: () =>
      selectedDeploymentId
        ? paperTradingApi.getPositions(selectedDeploymentId)
        : [],
    enabled: selectedDeploymentId !== null,
  });

  // Fetch orders for selected deployment
  const { data: orders = [] } = useQuery({
    queryKey: ["paper-orders", selectedDeploymentId],
    queryFn: () =>
      selectedDeploymentId
        ? paperTradingApi.getOrders(selectedDeploymentId)
        : [],
    enabled: selectedDeploymentId !== null,
  });

  // Filter deployments by status
  const filteredDeployments = deployments.filter((d) => {
    if (filterStatus === "all") return true;
    return d.status === filterStatus;
  });

  /**
   * Handle freeze deployment.
   */
  const handleFreeze = async () => {
    if (!selectedDeploymentId) return;

    setIsFreezingUnfreezing(true);
    try {
      await paperTradingApi.freezeDeployment(selectedDeploymentId);
      await refetchDetail();
    } catch (error) {
      console.error("Failed to freeze deployment:", error);
    } finally {
      setIsFreezingUnfreezing(false);
    }
  };

  /**
   * Handle unfreeze deployment.
   */
  const handleUnfreeze = async () => {
    if (!selectedDeploymentId) return;

    setIsFreezingUnfreezing(true);
    try {
      await paperTradingApi.unfreezeDeployment(selectedDeploymentId);
      await refetchDetail();
    } catch (error) {
      console.error("Failed to unfreeze deployment:", error);
    } finally {
      setIsFreezingUnfreezing(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-gray-900 text-gray-100">
      {/* Header */}
      <div className="border-b border-gray-700 px-4 py-3">
        <div className="mb-3 flex items-center justify-between">
          <h1 className="text-lg font-bold">Paper Trading Monitor</h1>
          <button
            className="flex items-center gap-2 rounded bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            onClick={() => {
              // Navigate to create new deployment
              console.log("Create new deployment");
            }}
            aria-label="Create new paper trading deployment"
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        </div>

        {/* Filter chips */}
        <div className="flex gap-2 overflow-x-auto pb-1">
          {(["all", "active", "frozen", "stopped"] as const).map((status) => (
            <button
              key={status}
              onClick={() => setFilterStatus(status as FilterStatus)}
              className={`whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                filterStatus === status
                  ? "bg-blue-600 text-white"
                  : "bg-gray-700 text-gray-300 hover:bg-gray-600"
              }`}
              aria-pressed={filterStatus === status}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {deploymentsError && (
          <div className="rounded bg-red-500/20 p-3 text-sm text-red-300">
            Failed to load deployments. Please try again.
          </div>
        )}

        {isLoadingDeployments ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-32 animate-pulse rounded-lg bg-gray-700"
              />
            ))}
          </div>
        ) : filteredDeployments.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-gray-400">
                {filterStatus === "all"
                  ? "No paper trading deployments yet."
                  : `No ${filterStatus} deployments.`}
              </p>
              <button
                className="mt-3 rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                onClick={() => {
                  // Navigate to create new deployment
                  console.log("Create new deployment");
                }}
              >
                Create One
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredDeployments.map((deployment) => (
              <DeploymentCard
                key={deployment.id}
                deployment={deployment}
                onClick={setSelectedDeploymentId}
              />
            ))}
          </div>
        )}
      </div>

      {/* Detail Modal / BottomSheet */}
      {selectedDeploymentId && selectedDeployment && (
        <div className="fixed inset-0 z-50 flex items-end bg-black/50">
          <div className="w-full rounded-t-lg bg-gray-800 p-4 max-h-[80vh] overflow-y-auto">
            {/* Close button */}
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold">Deployment Details</h2>
              <button
                onClick={() => setSelectedDeploymentId(null)}
                className="rounded px-2 py-1 text-gray-400 hover:bg-gray-700 hover:text-gray-100"
                aria-label="Close detail view"
              >
                ✕
              </button>
            </div>

            {/* Detail component */}
            {isLoadingDetail ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="h-20 animate-pulse rounded bg-gray-700"
                  />
                ))}
              </div>
            ) : (
              <DeploymentDetail
                deployment={selectedDeployment}
                positions={positions}
                orders={orders}
                isLoading={isFreezingUnfreezing}
                onFreeze={handleFreeze}
                onUnfreeze={handleUnfreeze}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
