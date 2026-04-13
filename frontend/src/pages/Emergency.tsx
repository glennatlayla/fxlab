/**
 * Emergency Controls page — kill switch and emergency posture management.
 *
 * Purpose:
 *   Provide a dedicated, mobile-first interface for emergency risk controls.
 *   Let operators activate/deactivate kill switches with safety confirmations.
 *
 * Responsibilities:
 *   - Fetch and display active kill switches via useQuery.
 *   - Render three activation panels (global, strategy, symbol).
 *   - Handle bottom sheet open/close for activation forms.
 *   - Validate reason input (minimum 10 characters).
 *   - Call emergencyApi on slide-to-confirm.
 *   - Show loading, error, and empty states.
 *   - Invalidate query after mutation to refresh list.
 *
 * Does NOT:
 *   - Contain kill switch logic (that's in emergencyApi).
 *   - Authenticate requests (apiClient does this).
 *   - Retry on transient errors (useQuery/useMutation handle this).
 *
 * Dependencies:
 *   - React (useState, useCallback).
 *   - @tanstack/react-query (useQuery, useMutation, useQueryClient).
 *   - @/features/emergency/api: emergencyApi.
 *   - @/components/mobile/SlideToConfirm: slide-to-confirm gesture.
 *   - @/components/mobile/BottomSheet: bottom sheet overlay.
 *   - @/components/ui/LoadingState: loading skeleton.
 *   - @/components/ui/ErrorState: error display.
 *   - lucide-react: icons.
 *   - clsx: classname helper.
 *
 * Error conditions:
 *   - Network failure: show error state, retry available.
 *   - 409 Conflict: kill switch already active (user message).
 *   - 404 Not Found: strategy or symbol not found (user message).
 *   - 422 Invalid: malformed input (user message).
 *
 * Example:
 *   import Emergency from "@/pages/Emergency";
 *   <Route path="/emergency" element={<Emergency />} />
 */

import React, { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Lock } from "lucide-react";
import clsx from "clsx";
import { emergencyApi } from "@/features/emergency/api";
import type { KillSwitchStatus, KillSwitchScope } from "@/features/emergency/types";
import { BottomSheet } from "@/components/mobile/BottomSheet";
import { SlideToConfirm } from "@/components/mobile/SlideToConfirm";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";

// ---------------------------------------------------------------------------
// Internal state for bottom sheet
// ---------------------------------------------------------------------------

interface ActivationFormState {
  scope: "global" | "strategy" | "symbol" | null;
  reason: string;
  targetId: string; // For strategy/symbol activations
}

/**
 * Emergency Controls page component.
 *
 * Renders:
 *   1. Active Kill Switches section — list of currently halted switches
 *   2. Activation Controls section — three cards for scope selection
 *   3. Bottom Sheet — form for entering reason and confirming activation
 *
 * Query/Mutation lifecycle:
 *   - GET /kill-switch/status (useQuery, refetch on mount, retry on failure)
 *   - POST /kill-switch/{scope}/{target} (useMutation, invalidate query after)
 *   - DELETE /kill-switch/{scope}/{target_id} (useMutation, invalidate query after)
 *
 * Example usage:
 *   <Emergency />
 */
export default function Emergency(): React.ReactElement {
  // =========================================================================
  // Query and mutation setup
  // =========================================================================

  const queryClient = useQueryClient();

  const {
    data: killSwitches = [],
    isLoading: isLoadingStatus,
    error: statusError,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ["emergency", "kill-switches"],
    queryFn: () => emergencyApi.getStatus(),
    refetchInterval: 5000, // Poll every 5 seconds for real-time status
  });

  const activateGlobalMutation = useMutation({
    mutationFn: (reason: string) => emergencyApi.activateGlobal(reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["emergency", "kill-switches"] });
      setFormState({ scope: null, reason: "", targetId: "" });
    },
  });

  const activateStrategyMutation = useMutation({
    mutationFn: ({ strategyId, reason }: { strategyId: string; reason: string }) =>
      emergencyApi.activateStrategy(strategyId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["emergency", "kill-switches"] });
      setFormState({ scope: null, reason: "", targetId: "" });
    },
  });

  const activateSymbolMutation = useMutation({
    mutationFn: ({ symbol, reason }: { symbol: string; reason: string }) =>
      emergencyApi.activateSymbol(symbol, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["emergency", "kill-switches"] });
      setFormState({ scope: null, reason: "", targetId: "" });
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: ({ scope, targetId }: { scope: string; targetId: string }) =>
      emergencyApi.deactivate(scope, targetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["emergency", "kill-switches"] });
    },
  });

  // =========================================================================
  // Local state
  // =========================================================================

  const [formState, setFormState] = useState<ActivationFormState>({
    scope: null,
    reason: "",
    targetId: "",
  });

  // =========================================================================
  // Handlers
  // =========================================================================

  /**
   * Open bottom sheet for a specific activation scope.
   */
  const handleOpenActivation = useCallback((scope: "global" | "strategy" | "symbol") => {
    setFormState({ scope, reason: "", targetId: "" });
  }, []);

  /**
   * Close bottom sheet without activating.
   */
  const handleCloseActivation = useCallback(() => {
    setFormState({ scope: null, reason: "", targetId: "" });
  }, []);

  /**
   * Handle slide-to-confirm for activation.
   * Calls the appropriate mutation based on scope.
   */
  const handleConfirmActivation = useCallback(() => {
    if (!formState.scope || !formState.reason.trim()) {
      return;
    }

    const reason = formState.reason.trim();

    switch (formState.scope) {
      case "global":
        activateGlobalMutation.mutate(reason);
        break;
      case "strategy":
        if (!formState.targetId.trim()) return;
        activateStrategyMutation.mutate({
          strategyId: formState.targetId.trim(),
          reason,
        });
        break;
      case "symbol":
        if (!formState.targetId.trim()) return;
        activateSymbolMutation.mutate({
          symbol: formState.targetId.trim(),
          reason,
        });
        break;
    }
  }, [formState, activateGlobalMutation, activateStrategyMutation, activateSymbolMutation]);

  /**
   * Handle deactivation via slide-to-confirm.
   */
  const handleConfirmDeactivation = useCallback(
    (killSwitch: KillSwitchStatus) => {
      deactivateMutation.mutate({
        scope: killSwitch.scope,
        targetId: killSwitch.target_id,
      });
    },
    [deactivateMutation],
  );

  // =========================================================================
  // Validation helpers
  // =========================================================================

  const isReasonValid = formState.reason.trim().length >= 10;
  const isTargetIdValid = formState.targetId.trim().length > 0;

  const canActivate =
    isReasonValid &&
    (formState.scope === "global" ||
      (formState.scope === "strategy" && isTargetIdValid) ||
      (formState.scope === "symbol" && isTargetIdValid));

  // =========================================================================
  // Render
  // =========================================================================

  return (
    <div className="min-h-screen bg-surface-50 px-4 py-6">
      <div className="mx-auto max-w-2xl space-y-6">
        {/* Header */}
        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-surface-900">Emergency Controls</h1>
          <p className="text-sm text-surface-500">
            Risk management and emergency posture controls. Use with caution.
          </p>
        </div>

        {/* ================================================================= */}
        {/* Active Kill Switches Section */}
        {/* ================================================================= */}

        <section className="space-y-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-surface-900">
            <Lock className="h-5 w-5 text-red-600" />
            Active Kill Switches
          </h2>

          {isLoadingStatus ? (
            <LoadingState message="Loading kill switch status..." />
          ) : statusError ? (
            <ErrorState
              message="Error fetching current kill switch status. Please try again."
              onRetry={() => refetchStatus()}
            />
          ) : killSwitches.length === 0 ? (
            <EmptyState
              title="No active kill switches"
              description="Trading is operating normally. All systems are active."
            />
          ) : (
            <div className="space-y-3">
              {killSwitches.map((killSwitch) => (
                <KillSwitchCard
                  key={`${killSwitch.scope}:${killSwitch.target_id}`}
                  killSwitch={killSwitch}
                  onDeactivate={() => handleConfirmDeactivation(killSwitch)}
                  isDeactivating={deactivateMutation.isPending}
                />
              ))}
            </div>
          )}
        </section>

        {/* ================================================================= */}
        {/* Activation Controls Section */}
        {/* ================================================================= */}

        <section className="space-y-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-surface-900">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            Activate Controls
          </h2>

          <div className="grid grid-cols-1 gap-3">
            {/* Global Activation Card */}
            <button
              onClick={() => handleOpenActivation("global")}
              disabled={activateGlobalMutation.isPending}
              className={clsx(
                "rounded-lg border-2 border-red-200 bg-red-50 p-4 text-left",
                "hover:border-red-400 active:bg-red-100",
                "disabled:cursor-not-allowed disabled:opacity-50",
                "transition-colors",
              )}
            >
              <div className="font-semibold text-red-900">Global Kill Switch</div>
              <div className="mt-1 text-sm text-red-700">
                Halt all trading across all deployments
              </div>
            </button>

            {/* Strategy Activation Card */}
            <button
              onClick={() => handleOpenActivation("strategy")}
              disabled={activateStrategyMutation.isPending}
              className={clsx(
                "rounded-lg border-2 border-amber-200 bg-amber-50 p-4 text-left",
                "hover:border-amber-400 active:bg-amber-100",
                "disabled:cursor-not-allowed disabled:opacity-50",
                "transition-colors",
              )}
            >
              <div className="font-semibold text-amber-900">Strategy Kill Switch</div>
              <div className="mt-1 text-sm text-amber-700">Halt a specific strategy by ID</div>
            </button>

            {/* Symbol Activation Card */}
            <button
              onClick={() => handleOpenActivation("symbol")}
              disabled={activateSymbolMutation.isPending}
              className={clsx(
                "rounded-lg border-2 border-orange-200 bg-orange-50 p-4 text-left",
                "hover:border-orange-400 active:bg-orange-100",
                "disabled:cursor-not-allowed disabled:opacity-50",
                "transition-colors",
              )}
            >
              <div className="font-semibold text-orange-900">Symbol Kill Switch</div>
              <div className="mt-1 text-sm text-orange-700">Halt trading on a specific symbol</div>
            </button>
          </div>
        </section>
      </div>

      {/* ================================================================= */}
      {/* Bottom Sheet for Activation Form */}
      {/* ================================================================= */}

      <BottomSheet
        isOpen={formState.scope !== null}
        onClose={handleCloseActivation}
        title={
          formState.scope === "global"
            ? "Activate Global Kill Switch"
            : formState.scope === "strategy"
              ? "Activate Strategy Kill Switch"
              : "Activate Symbol Kill Switch"
        }
      >
        <div className="space-y-4">
          {/* Target ID Input (for strategy/symbol) */}
          {(formState.scope === "strategy" || formState.scope === "symbol") && (
            <div>
              <label className="mb-2 block text-sm font-medium text-surface-900">
                {formState.scope === "strategy" ? "Strategy ID" : "Symbol"}
              </label>
              <input
                type="text"
                placeholder={formState.scope === "strategy" ? "e.g., 01HS123ABC" : "e.g., AAPL"}
                value={formState.targetId}
                onChange={(e) =>
                  setFormState((prev) => ({
                    ...prev,
                    targetId: e.target.value,
                  }))
                }
                className={clsx(
                  "w-full rounded-lg border px-4 py-2 font-mono text-sm",
                  "border-surface-300 bg-white text-surface-900",
                  "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500",
                )}
              />
            </div>
          )}

          {/* Reason Input */}
          <div>
            <label className="mb-2 block text-sm font-medium text-surface-900">
              Reason (min 10 characters)
            </label>
            <textarea
              placeholder="Explain why you are activating this kill switch..."
              value={formState.reason}
              onChange={(e) =>
                setFormState((prev) => ({
                  ...prev,
                  reason: e.target.value,
                }))
              }
              rows={4}
              className={clsx(
                "w-full rounded-lg border px-4 py-2 text-sm",
                "border-surface-300 bg-white text-surface-900",
                "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500",
                "resize-none",
              )}
            />
            <div className="mt-1 text-xs text-surface-500">
              {formState.reason.length}/10 characters
            </div>
          </div>

          {/* Validation Message */}
          {formState.reason.trim().length > 0 && !isReasonValid && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              Reason must be at least 10 characters long.
            </div>
          )}

          {formState.scope !== "global" && formState.targetId.trim().length === 0 && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {formState.scope === "strategy" ? "Strategy ID" : "Symbol"} is required.
            </div>
          )}

          {/* Slide to Confirm */}
          <div className="border-t border-surface-200 pt-4">
            <SlideToConfirm
              label="Slide to activate"
              variant="danger"
              disabled={
                !canActivate ||
                activateGlobalMutation.isPending ||
                activateStrategyMutation.isPending ||
                activateSymbolMutation.isPending
              }
              onConfirm={handleConfirmActivation}
            />
          </div>
        </div>
      </BottomSheet>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Kill Switch Card Component
// ---------------------------------------------------------------------------

interface KillSwitchCardProps {
  killSwitch: KillSwitchStatus;
  onDeactivate: () => void;
  isDeactivating: boolean;
}

/**
 * Display a single active kill switch with deactivation option.
 *
 * Args:
 *   killSwitch: The kill switch status to display.
 *   onDeactivate: Callback when deactivate button is clicked.
 *   isDeactivating: Whether deactivation is in progress.
 */
function KillSwitchCard({
  killSwitch,
  onDeactivate,
  isDeactivating,
}: KillSwitchCardProps): React.ReactElement {
  const scopeBadgeColor: Record<KillSwitchScope, string> = {
    global: "bg-red-100 text-red-800",
    strategy: "bg-amber-100 text-amber-800",
    symbol: "bg-orange-100 text-orange-800",
  };

  return (
    <div className="space-y-3 rounded-lg border border-surface-200 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          <div className="flex items-center gap-2">
            <span
              className={clsx(
                "rounded px-2 py-1 text-sm font-medium",
                scopeBadgeColor[killSwitch.scope],
              )}
            >
              {killSwitch.scope.toUpperCase()}
            </span>
            {killSwitch.target_id !== "global" && (
              <code className="rounded bg-surface-100 px-2 py-1 font-mono text-xs text-surface-700">
                {killSwitch.target_id}
              </code>
            )}
          </div>
          <div>
            <p className="text-sm font-medium text-surface-900">{killSwitch.reason}</p>
            <p className="mt-1 text-xs text-surface-500">
              {killSwitch.activated_by ? `Activated by ${killSwitch.activated_by}` : "Activated"}
              {killSwitch.activated_at &&
                ` at ${new Date(killSwitch.activated_at).toLocaleTimeString()}`}
            </p>
          </div>
        </div>

        {/* Deactivate Button */}
        <button
          onClick={onDeactivate}
          disabled={isDeactivating}
          className={clsx(
            "rounded-lg px-3 py-2 text-sm font-medium",
            "bg-red-100 text-red-700 hover:bg-red-200 active:bg-red-300",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "whitespace-nowrap transition-colors",
          )}
        >
          {isDeactivating ? "Deactivating..." : "Deactivate"}
        </button>
      </div>
    </div>
  );
}
