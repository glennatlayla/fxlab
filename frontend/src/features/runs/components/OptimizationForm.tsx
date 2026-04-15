/**
 * OptimizationForm component (FE-15).
 *
 * Purpose:
 * - Comprehensive optimization run submission form
 * - Extends backtest form with optimization-specific fields
 * - Provides metric selection, parameter grid editor, trial estimation
 * - Optional walk-forward and monte carlo configuration
 *
 * Responsibilities:
 * - Render all form fields for optimization setup
 * - Manage form state using React hooks
 * - Validate form using Zod schema
 * - Submit valid config to parent callback
 * - Show validation errors and loading state
 *
 * Does NOT:
 * - Call APIs directly (delegates to parent via onSubmit callback)
 * - Manage run state or polling
 * - Store form state persistently
 *
 * Dependencies:
 * - React hooks for form state management
 * - zod for validation schema
 * - optimisation.ts for domain types
 * - optimisation.validation.ts for schema
 * - ParameterRangeEditor, TrialEstimator components
 * - lucide-react for icons
 * - Tailwind CSS for styling
 *
 * Example:
 *   <OptimizationForm
 *     strategyBuildId="01HSTRATEGY..."
 *     onSubmit={async (values) => {
 *       const response = await submitOptimization(values);
 *       // Handle response
 *     }}
 *     isSubmitting={isLoading}
 *   />
 */

import React, { useState, useCallback } from "react";
import { ChevronDown, ChevronUp, Loader } from "lucide-react";
import { validateOptimizationForm } from "../optimisation.validation";
import {
  VALID_INTERVALS,
  VALID_METRICS,
} from "../optimisation.validation";
import { ParameterRangeEditor } from "./ParameterRangeEditor";
import { TrialEstimator } from "./TrialEstimator";
import type { OptimizationFormValues } from "../optimisation";

export interface OptimizationFormProps {
  /** ULID of the strategy build to execute. */
  strategyBuildId: string;
  /** Callback on successful form submission. */
  onSubmit: (values: OptimizationFormValues) => Promise<void>;
  /** Whether a submission is currently in progress. */
  isSubmitting?: boolean;
  /** Optional CSS class names. */
  className?: string;
}

/**
 * OptimizationForm — comprehensive optimization setup form.
 *
 * Renders:
 * - Backtest fields: symbols, dates, interval, initial equity
 * - Optimization fields: metric picker, parameter grid editor
 * - Trial estimator with severity color coding
 * - Collapsible optional sections: walk-forward, monte carlo
 * - Sticky submit button for mobile
 *
 * Validates:
 * - All required fields
 * - Parameter constraints (min < max, step > 0)
 * - Trial count limits
 * - Walk-forward and monte carlo ranges
 *
 * Example:
 *   <OptimizationForm
 *     strategyBuildId={selectedStrategy}
 *     onSubmit={handleSubmit}
 *     isSubmitting={isLoading}
 *   />
 */
export function OptimizationForm({
  strategyBuildId,
  onSubmit,
  isSubmitting = false,
  className,
}: OptimizationFormProps): React.ReactElement {
  // Form state
  const [formValues, setFormValues] = useState<Partial<OptimizationFormValues>>({
    strategy_build_id: strategyBuildId,
    symbols: [],
    start_date: "",
    end_date: "",
    interval: "1d",
    initial_equity: 100000,
    optimization_metric: "sharpe_ratio",
    parameters: [],
  });

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [expandWalkForward, setExpandWalkForward] = useState(false);
  const [expandMonteCarlo, setExpandMonteCarlo] = useState(false);

  // Validate on blur
  const validateForm = useCallback(() => {
    const result = validateOptimizationForm(formValues);

    if (!result.success) {
      const errors: Record<string, string> = {};
      const flattened = result.error.flatten();

      Object.entries(flattened.fieldErrors).forEach(([field, messages]) => {
        if (Array.isArray(messages) && messages.length > 0) {
          errors[field] = messages[0];
        }
      });

      setFieldErrors(errors);
      return false;
    }

    setFieldErrors({});
    return true;
  }, [formValues]);

  const handleSymbolsChange = useCallback((value: string) => {
    const symbols = value
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    setFormValues((prev) => ({
      ...prev,
      symbols,
    }));
  }, []);

  const handleFieldChange = useCallback(
    (field: keyof OptimizationFormValues, value: unknown) => {
      setFormValues((prev) => ({
        ...prev,
        [field]: value,
      }));
    },
    []
  );

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!validateForm()) {
        return;
      }

      try {
        await onSubmit(formValues as OptimizationFormValues);
      } catch (error) {
        console.error("Form submission failed:", error);
      }
    },
    [formValues, validateForm, onSubmit]
  );

  const parameters = formValues.parameters || [];
  const errorCount = Object.keys(fieldErrors).length;

  const getFieldError = (field: string): string | undefined => {
    return fieldErrors[field];
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={`${className || ""} pb-32`}
    >
      {/* Error summary */}
      {errorCount > 0 && (
        <div className="mb-6 rounded-lg bg-red-50 border border-red-200 p-4">
          <p className="text-sm font-medium text-red-900">
            {errorCount} error{errorCount !== 1 ? "s" : ""} in form. Please
            review and correct before submitting.
          </p>
        </div>
      )}

      {/* Backtest section */}
      <div className="space-y-5 mb-8">
        <h2 className="text-lg font-semibold text-gray-900">
          Backtest Configuration
        </h2>

        {/* Symbols */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Symbols
          </label>
          <input
            type="text"
            placeholder="AAPL, MSFT, GOOGL"
            value={
              Array.isArray(formValues.symbols)
                ? formValues.symbols.join(", ")
                : ""
            }
            onChange={(e) => handleSymbolsChange(e.target.value)}
            className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              getFieldError("symbols") ? "border-red-500" : "border-gray-300"
            }`}
          />
          {getFieldError("symbols") && (
            <p className="text-xs text-red-600 mt-1">
              {getFieldError("symbols")}
            </p>
          )}
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Start Date
            </label>
            <input
              type="date"
              value={formValues.start_date || ""}
              onChange={(e) =>
                handleFieldChange("start_date", e.target.value)
              }
              className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                getFieldError("start_date")
                  ? "border-red-500"
                  : "border-gray-300"
              }`}
            />
            {getFieldError("start_date") && (
              <p className="text-xs text-red-600 mt-1">
                {getFieldError("start_date")}
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              End Date
            </label>
            <input
              type="date"
              value={formValues.end_date || ""}
              onChange={(e) => handleFieldChange("end_date", e.target.value)}
              className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                getFieldError("end_date") ? "border-red-500" : "border-gray-300"
              }`}
            />
            {getFieldError("end_date") && (
              <p className="text-xs text-red-600 mt-1">
                {getFieldError("end_date")}
              </p>
            )}
          </div>
        </div>

        {/* Interval */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Interval
          </label>
          <select
            value={formValues.interval || "1d"}
            onChange={(e) => handleFieldChange("interval", e.target.value)}
            className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              getFieldError("interval") ? "border-red-500" : "border-gray-300"
            }`}
          >
            {VALID_INTERVALS.map((interval) => (
              <option key={interval} value={interval}>
                {interval}
              </option>
            ))}
          </select>
        </div>

        {/* Initial equity */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Initial Equity
          </label>
          <input
            type="number"
            value={formValues.initial_equity || ""}
            onChange={(e) =>
              handleFieldChange("initial_equity", parseFloat(e.target.value))
            }
            step="100"
            className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              getFieldError("initial_equity")
                ? "border-red-500"
                : "border-gray-300"
            }`}
          />
        </div>
      </div>

      {/* Optimization section */}
      <div className="space-y-5 mb-8">
        <h2 className="text-lg font-semibold text-gray-900">
          Optimization Configuration
        </h2>

        {/* Optimization metric */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Optimization Metric
          </label>
          <select
            value={formValues.optimization_metric || "sharpe_ratio"}
            onChange={(e) =>
              handleFieldChange("optimization_metric", e.target.value)
            }
            className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {VALID_METRICS.map((metric) => (
              <option key={metric} value={metric}>
                {metric.replace(/_/g, " ").toUpperCase()}
              </option>
            ))}
          </select>
        </div>

        {/* Parameter ranges */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-3">
            Parameter Ranges
          </label>
          <ParameterRangeEditor
            parameters={parameters}
            onChange={(updated) =>
              handleFieldChange("parameters", updated)
            }
          />
          {getFieldError("parameters") && (
            <p className="text-xs text-red-600 mt-2">
              {getFieldError("parameters")}
            </p>
          )}
        </div>

        {/* Trial estimator */}
        {parameters.length > 0 && (
          <TrialEstimator parameters={parameters} />
        )}
      </div>

      {/* Walk-Forward section (collapsible) */}
      <div className="mb-8">
        <button
          type="button"
          onClick={() => setExpandWalkForward(!expandWalkForward)}
          className="w-full flex items-center justify-between p-4 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <h3 className="text-sm font-medium text-gray-900">
            Walk-Forward Analysis (Optional)
          </h3>
          {expandWalkForward ? (
            <ChevronUp className="w-5 h-5 text-gray-600" />
          ) : (
            <ChevronDown className="w-5 h-5 text-gray-600" />
          )}
        </button>

        {expandWalkForward && (
          <div className="mt-4 p-4 border border-gray-300 rounded-lg bg-gray-50 space-y-4">
            {/* Walk-forward windows */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Rolling Windows
              </label>
              <input
                type="number"
                value={formValues.walk_forward_windows ?? ""}
                onChange={(e) =>
                  handleFieldChange(
                    "walk_forward_windows",
                    e.target.value ? parseInt(e.target.value) : undefined
                  )
                }
                min="2"
                max="20"
                className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  getFieldError("walk_forward_windows")
                    ? "border-red-500"
                    : "border-gray-300"
                }`}
              />
              {getFieldError("walk_forward_windows") && (
                <p className="text-xs text-red-600 mt-1">
                  {getFieldError("walk_forward_windows")}
                </p>
              )}
            </div>

            {/* Walk-forward train percentage */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Training Percentage (%)
              </label>
              <input
                type="number"
                value={formValues.walk_forward_train_pct ?? ""}
                onChange={(e) =>
                  handleFieldChange(
                    "walk_forward_train_pct",
                    e.target.value ? parseFloat(e.target.value) : undefined
                  )
                }
                min="50"
                max="90"
                step="5"
                className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  getFieldError("walk_forward_train_pct")
                    ? "border-red-500"
                    : "border-gray-300"
                }`}
              />
              {getFieldError("walk_forward_train_pct") && (
                <p className="text-xs text-red-600 mt-1">
                  {getFieldError("walk_forward_train_pct")}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Monte Carlo section (collapsible) */}
      <div className="mb-8">
        <button
          type="button"
          onClick={() => setExpandMonteCarlo(!expandMonteCarlo)}
          className="w-full flex items-center justify-between p-4 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <h3 className="text-sm font-medium text-gray-900">
            Monte Carlo Simulation (Optional)
          </h3>
          {expandMonteCarlo ? (
            <ChevronUp className="w-5 h-5 text-gray-600" />
          ) : (
            <ChevronDown className="w-5 h-5 text-gray-600" />
          )}
        </button>

        {expandMonteCarlo && (
          <div className="mt-4 p-4 border border-gray-300 rounded-lg bg-gray-50 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Number of Runs
              </label>
              <input
                type="number"
                value={formValues.monte_carlo_runs ?? ""}
                onChange={(e) =>
                  handleFieldChange(
                    "monte_carlo_runs",
                    e.target.value ? parseInt(e.target.value) : undefined
                  )
                }
                min="100"
                step="100"
                className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  getFieldError("monte_carlo_runs")
                    ? "border-red-500"
                    : "border-gray-300"
                }`}
              />
              {getFieldError("monte_carlo_runs") && (
                <p className="text-xs text-red-600 mt-1">
                  {getFieldError("monte_carlo_runs")}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Sticky submit button */}
      <div className="fixed bottom-0 left-0 right-0 border-t border-gray-200 bg-white p-4">
        <button
          type="submit"
          disabled={isSubmitting}
          className={`w-full py-3 px-4 rounded-lg font-medium text-white flex items-center justify-center gap-2 transition-colors ${
            isSubmitting
              ? "bg-gray-400 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          {isSubmitting && <Loader className="w-4 h-4 animate-spin" />}
          {isSubmitting ? "Submitting..." : "Submit Optimization"}
        </button>
      </div>
    </form>
  );
}
