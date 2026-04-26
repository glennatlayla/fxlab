/**
 * PaperTradingForm — Main form for paper trading setup.
 *
 * Purpose:
 *   Collect user inputs for paper trading registration:
 *   deployment, strategy, initial equity, risk limits, and symbols.
 *   Provides mobile-optimized pickers for selection fields.
 *
 * Responsibilities:
 *   - Render form fields for all required inputs.
 *   - Open BottomSheet pickers for deployment and strategy selection.
 *   - Track form state with controlled inputs.
 *   - Validate inputs using Zod schema.
 *   - Show field-level validation errors.
 *   - Disable submit until all required fields are set and valid.
 *   - Call onSubmit callback with validated config.
 *
 * Does NOT:
 *   - Make API calls directly (handled by parent).
 *   - Manage global state.
 *   - Execute business logic.
 *
 * Dependencies:
 *   - React (useState, useCallback).
 *   - BottomSheet component.
 *   - paperTradingConfigSchema for validation.
 *   - types: DeploymentMetadata, StrategyBuildMetadata, PaperTradingConfig.
 *
 * Error conditions:
 *   - Validation errors: displayed below each field.
 *   - API errors: displayed via error prop.
 *
 * Example:
 *   <PaperTradingForm
 *     deployments={[...]}
 *     strategies={[...]}
 *     isLoading={false}
 *     onSubmit={handleSubmit}
 *   />
 */

import React, { useState, useCallback } from "react";
import { BottomSheet } from "@/components/mobile/BottomSheet";
import { paperTradingConfigSchema } from "../validation";
import type { DeploymentMetadata, StrategyBuildMetadata, PaperTradingConfig } from "../types";

export interface PaperTradingFormProps {
  /** List of available deployments for selection. */
  deployments: DeploymentMetadata[];
  /** List of available strategies for selection. */
  strategies: StrategyBuildMetadata[];
  /** Whether form submission is in progress. */
  isLoading: boolean;
  /** Callback when form is submitted with valid data. */
  onSubmit: (config: PaperTradingConfig) => void;
  /** Optional error message to display. */
  error?: string | null;
}

/**
 * PaperTradingForm component.
 *
 * Renders a mobile-optimized form for paper trading setup.
 * Collects deployment, strategy, initial equity, risk limits, and symbols.
 *
 * Example:
 *   <PaperTradingForm
 *     deployments={deployments}
 *     strategies={strategies}
 *     isLoading={isSubmitting}
 *     onSubmit={handleSubmit}
 *   />
 */
export function PaperTradingForm({
  deployments,
  strategies,
  isLoading,
  onSubmit,
  error,
}: PaperTradingFormProps): React.ReactElement {
  // Form state
  const [selectedDeploymentId, setSelectedDeploymentId] = useState<string>("");
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("");
  const [initialEquity, setInitialEquity] = useState<number>(10000);
  const [maxPositionSize, setMaxPositionSize] = useState<number>(5000);
  const [maxDailyLoss, setMaxDailyLoss] = useState<number>(1000);
  const [maxLeverage, setMaxLeverage] = useState<number>(2);
  const [symbolsInput, setSymbolsInput] = useState<string>("AAPL,MSFT");

  // UI state
  const [showDeploymentPicker, setShowDeploymentPicker] = useState(false);
  const [showStrategyPicker, setShowStrategyPicker] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Get selected deployment and strategy names for display
  const selectedDeployment = deployments.find((d) => d.id === selectedDeploymentId);
  const selectedStrategy = strategies.find((s) => s.id === selectedStrategyId);

  /**
   * Validate and submit the form.
   */
  const handleSubmit = useCallback(() => {
    // Parse symbols from comma-separated input
    const symbols = symbolsInput
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    // Build config
    const config: PaperTradingConfig = {
      deployment_id: selectedDeploymentId,
      strategy_build_id: selectedStrategyId,
      initial_equity: initialEquity,
      max_position_size: maxPositionSize,
      max_daily_loss: maxDailyLoss,
      max_leverage: maxLeverage,
      symbols,
    };

    // Validate using schema
    const result = paperTradingConfigSchema.safeParse(config);
    if (!result.success) {
      const errors: Record<string, string> = {};
      const flatErrors = result.error.flatten().fieldErrors;
      Object.entries(flatErrors).forEach(([key, msgs]) => {
        if (msgs && msgs.length > 0) {
          errors[key] = msgs[0];
        }
      });
      setFieldErrors(errors);
      return;
    }

    // Clear errors and call onSubmit
    setFieldErrors({});
    onSubmit(result.data);
  }, [
    selectedDeploymentId,
    selectedStrategyId,
    initialEquity,
    maxPositionSize,
    maxDailyLoss,
    maxLeverage,
    symbolsInput,
    onSubmit,
  ]);

  /**
   * Check if form is complete enough to submit.
   */
  const isFormValid =
    selectedDeploymentId &&
    selectedStrategyId &&
    initialEquity >= 1000 &&
    maxLeverage >= 1 &&
    maxLeverage <= 10 &&
    symbolsInput.trim().length > 0;

  return (
    <div className="flex flex-col gap-6 p-4">
      {/* Error banner */}
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Deployment Picker */}
      <div>
        <label className="mb-2 block text-sm font-medium text-surface-900">
          Deployment <span className="text-red-600">*</span>
        </label>
        <button
          onClick={() => setShowDeploymentPicker(true)}
          className="w-full rounded-lg border border-surface-300 bg-white px-4 py-3 text-left transition-colors hover:bg-surface-50"
          aria-label="Select deployment"
        >
          {selectedDeployment ? selectedDeployment.name : "Select a deployment"}
        </button>
        {fieldErrors.deployment_id && (
          <p className="mt-1 text-sm text-red-600">{fieldErrors.deployment_id}</p>
        )}
      </div>

      <BottomSheet
        isOpen={showDeploymentPicker}
        onClose={() => setShowDeploymentPicker(false)}
        title="Select Deployment"
      >
        <div className="flex flex-col gap-2">
          {deployments.map((deployment) => (
            <button
              key={deployment.id}
              onClick={() => {
                setSelectedDeploymentId(deployment.id);
                setShowDeploymentPicker(false);
              }}
              className="rounded-lg border border-surface-200 p-3 text-left transition-colors hover:bg-surface-50"
            >
              <div className="font-medium text-surface-900">{deployment.name}</div>
              <div className="mt-1 text-xs text-surface-500">Status: {deployment.status}</div>
            </button>
          ))}
        </div>
      </BottomSheet>

      {/* Strategy Picker */}
      <div>
        <label className="mb-2 block text-sm font-medium text-surface-900">
          Strategy <span className="text-red-600">*</span>
        </label>
        <button
          onClick={() => setShowStrategyPicker(true)}
          className="w-full rounded-lg border border-surface-300 bg-white px-4 py-3 text-left transition-colors hover:bg-surface-50"
          aria-label="Select strategy"
        >
          {selectedStrategy ? selectedStrategy.name : "Select a strategy"}
        </button>
        {fieldErrors.strategy_build_id && (
          <p className="mt-1 text-sm text-red-600">{fieldErrors.strategy_build_id}</p>
        )}
      </div>

      <BottomSheet
        isOpen={showStrategyPicker}
        onClose={() => setShowStrategyPicker(false)}
        title="Select Strategy"
      >
        <div className="flex flex-col gap-2">
          {strategies.map((strategy) => (
            <button
              key={strategy.id}
              onClick={() => {
                setSelectedStrategyId(strategy.id);
                setShowStrategyPicker(false);
              }}
              className="rounded-lg border border-surface-200 p-3 text-left transition-colors hover:bg-surface-50"
            >
              <div className="font-medium text-surface-900">{strategy.name}</div>
              {strategy.version && (
                <div className="mt-1 text-xs text-surface-500">Version: {strategy.version}</div>
              )}
            </button>
          ))}
        </div>
      </BottomSheet>

      {/* Initial Equity */}
      <div>
        <label className="mb-2 block text-sm font-medium text-surface-900">
          Initial Equity <span className="text-red-600">*</span>
        </label>
        <div className="relative">
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-surface-600">$</span>
          <input
            type="number"
            min="1000"
            max="1000000"
            value={initialEquity}
            onChange={(e) => setInitialEquity(Number(e.target.value))}
            className="w-full rounded-lg border border-surface-300 bg-white py-3 pl-8 pr-4 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            aria-label="Initial equity"
          />
        </div>
        {fieldErrors.initial_equity && (
          <p className="mt-1 text-sm text-red-600">{fieldErrors.initial_equity}</p>
        )}
      </div>

      {/* Risk Limits Section */}
      <div className="border-t border-surface-200 pt-4">
        <h3 className="mb-4 text-sm font-semibold text-surface-900">Risk Limits</h3>

        {/* Max Position Size */}
        <div className="mb-4">
          <label className="mb-2 block text-sm font-medium text-surface-900">
            Max Position Size
          </label>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-surface-600">$</span>
            <input
              type="number"
              min="0"
              step="100"
              value={maxPositionSize}
              onChange={(e) => setMaxPositionSize(Number(e.target.value))}
              className="w-full rounded-lg border border-surface-300 bg-white py-3 pl-8 pr-4 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          {fieldErrors.max_position_size && (
            <p className="mt-1 text-sm text-red-600">{fieldErrors.max_position_size}</p>
          )}
        </div>

        {/* Max Daily Loss */}
        <div className="mb-4">
          <label className="mb-2 block text-sm font-medium text-surface-900">Max Daily Loss</label>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-surface-600">$</span>
            <input
              type="number"
              min="0"
              step="100"
              value={maxDailyLoss}
              onChange={(e) => setMaxDailyLoss(Number(e.target.value))}
              className="w-full rounded-lg border border-surface-300 bg-white py-3 pl-8 pr-4 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          {fieldErrors.max_daily_loss && (
            <p className="mt-1 text-sm text-red-600">{fieldErrors.max_daily_loss}</p>
          )}
        </div>

        {/* Max Leverage */}
        <div>
          <label className="mb-2 block text-sm font-medium text-surface-900">
            Max Leverage: {maxLeverage.toFixed(1)}x
          </label>
          <input
            type="range"
            min="1"
            max="10"
            step="0.5"
            value={maxLeverage}
            onChange={(e) => setMaxLeverage(Number(e.target.value))}
            className="w-full"
            aria-label="Leverage"
          />
          <div className="mt-1 flex justify-between text-xs text-surface-500">
            <span>1x</span>
            <span>10x</span>
          </div>
          {fieldErrors.max_leverage && (
            <p className="mt-1 text-sm text-red-600">{fieldErrors.max_leverage}</p>
          )}
        </div>
      </div>

      {/* Symbols */}
      <div>
        <label className="mb-2 block text-sm font-medium text-surface-900">
          Trading Symbols <span className="text-red-600">*</span>
        </label>
        <input
          type="text"
          placeholder="AAPL,MSFT,GOOGL"
          value={symbolsInput}
          onChange={(e) => setSymbolsInput(e.target.value)}
          className="w-full rounded-lg border border-surface-300 bg-white px-4 py-3 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <p className="mt-1 text-xs text-surface-500">Comma-separated list of symbols</p>
        {fieldErrors.symbols && <p className="mt-1 text-sm text-red-600">{fieldErrors.symbols}</p>}
      </div>

      {/* Submit Button */}
      <button
        onClick={handleSubmit}
        disabled={!isFormValid || isLoading}
        className="w-full rounded-lg bg-brand-500 py-3 font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-surface-300 disabled:text-surface-500"
      >
        {isLoading ? "Loading..." : "Continue to Review"}
      </button>
    </div>
  );
}
