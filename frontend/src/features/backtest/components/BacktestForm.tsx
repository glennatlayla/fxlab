/**
 * BacktestForm — Mobile-optimized backtest creation form (FE-08).
 *
 * Purpose:
 *   Provide a comprehensive form for creating and submitting backtests.
 *   Implements strategy picker, symbol picker, date range, time interval,
 *   and optional advanced settings (commission, slippage).
 *   All input is validated against Zod schema before submission.
 *
 * Responsibilities:
 *   - Render form fields with mobile-friendly layout.
 *   - Manage form state using React hooks.
 *   - Validate form input against backtestFormSchema.
 *   - Show inline validation errors.
 *   - Open BottomSheet pickers for strategy/symbol selection.
 *   - Submit validated form to backtestApi.submitBacktest.
 *   - Navigate to run detail page on success.
 *   - Call onError callback on submission failure.
 *
 * Does NOT:
 *   - Manage run polling or monitoring (see runs feature).
 *   - Contain business logic beyond form orchestration.
 *   - Make API calls except to backtestApi and strategyApi.
 *
 * Dependencies:
 *   - React hooks (useState, useCallback, useEffect).
 *   - @tanstack/react-query (useMutation).
 *   - react-router-dom (useNavigate).
 *   - @/components/mobile/BottomSheet (picker sheets).
 *   - @/components/common/SegmentedControl (interval selector).
 *   - ../api (backtestApi).
 *   - ../validation (backtestFormSchema, validateBacktestForm).
 *   - ../types (BacktestFormValues, TIME_INTERVALS).
 *   - @/features/strategy/api (strategyApi).
 *
 * Error conditions:
 *   - Network errors on submission → onError callback.
 *   - Validation errors → shown inline on form.
 *
 * Example:
 *   <BacktestForm
 *     onSubmit={(formValues) => submitBacktest(formValues)}
 *     onError={(error) => showErrorToast(error.message)}
 *   />
 */

import React, { useState, useCallback, useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import clsx from "clsx";

import { BottomSheet } from "@/components/mobile/BottomSheet";
import { SegmentedControl } from "@/components/common/SegmentedControl";
import { backtestApi } from "../api";
import { validateBacktestForm } from "../validation";
import type { BacktestFormValues, TimeInterval } from "../types";
import { TIME_INTERVALS, DEFAULT_BACKTEST_FORM, BACKTEST_CONSTRAINTS } from "../types";

export interface BacktestFormProps {
  /** Callback after successful form submission. */
  onSubmit?: (formValues: BacktestFormValues, runId: string) => void;
  /** Callback when form submission fails. */
  onError?: (error: Error) => void;
  /** Optional CSS class names. */
  className?: string;
}

/** Placeholder data for strategy list (in real app, fetched from API). */
const MOCK_STRATEGIES = [
  { id: "strat-001", name: "RSI Reversal" },
  { id: "strat-002", name: "Moving Average Crossover" },
  { id: "strat-003", name: "Bollinger Band Bounce" },
];

/** Placeholder data for symbol list (in real app, fetched from feeds API). */
const MOCK_SYMBOLS = [
  "AAPL",
  "MSFT",
  "GOOGL",
  "AMZN",
  "TSLA",
  "META",
  "NFLX",
  "NVDA",
  "SPY",
  "QQQ",
];

/**
 * BacktestForm component.
 *
 * Renders a mobile-optimized form for creating research backtests.
 * Form state is managed locally with React hooks; submission goes through
 * backtestApi with full validation.
 */
export function BacktestForm({
  onSubmit: onSubmitProp,
  onError,
  className,
}: BacktestFormProps): React.ReactElement {
  const navigate = useNavigate();

  // ─────────────────────────────────────────────────────────────────────────
  // Form state
  // ─────────────────────────────────────────────────────────────────────────

  const [formValues, setFormValues] = useState<Partial<BacktestFormValues>>({
    ...DEFAULT_BACKTEST_FORM,
  });

  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});

  const [expandedAdvanced, setExpandedAdvanced] = useState(false);

  // Sheet state
  const [strategySheetOpen, setStrategySheetOpen] = useState(false);
  const [symbolSheetOpen, setSymbolSheetOpen] = useState(false);
  const [symbolSearch, setSymbolSearch] = useState("");

  // ─────────────────────────────────────────────────────────────────────────
  // Mutations
  // ─────────────────────────────────────────────────────────────────────────

  const { mutate: submitBacktest, isPending: isSubmitting } = useMutation({
    mutationFn: async (values: BacktestFormValues) => {
      return await backtestApi.submitBacktest(values);
    },
    onSuccess: (run) => {
      if (onSubmitProp) {
        onSubmitProp(formValues as BacktestFormValues, run.id);
      }
      // Navigate to run detail
      navigate(`/runs/${run.id}`);
    },
    onError: (error: Error) => {
      if (onError) {
        onError(error);
      }
    },
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Validation
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Validate entire form; return true if valid.
   * Updates fieldErrors state with any violations.
   */
  const validateForm = useCallback(
    (values: Partial<BacktestFormValues>): values is BacktestFormValues => {
      const result = validateBacktestForm(values);
      if (result.success) {
        setFieldErrors({});
        return true;
      }
      setFieldErrors(result.errors);
      return false;
    },
    [],
  );

  /**
   * Check if form is valid (without validation side effects).
   */
  const isFormValid = useMemo(() => {
    const result = validateBacktestForm(formValues);
    return result.success;
  }, [formValues]);

  /**
   * Get error message for a field (first error, if any).
   */
  const getFieldError = (fieldName: keyof BacktestFormValues): string | null => {
    const errors = fieldErrors[fieldName];
    return errors && errors.length > 0 ? errors[0] : null;
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Filtered symbols for picker
  // ─────────────────────────────────────────────────────────────────────────

  const filteredSymbols = useMemo(() => {
    if (!symbolSearch) return MOCK_SYMBOLS;
    return MOCK_SYMBOLS.filter((sym) => sym.toUpperCase().includes(symbolSearch.toUpperCase()));
  }, [symbolSearch]);

  // ─────────────────────────────────────────────────────────────────────────
  // Event handlers
  // ─────────────────────────────────────────────────────────────────────────

  const handleStrategySelect = (strategyId: string) => {
    setFormValues((prev) => ({ ...prev, strategy_build_id: strategyId }));
    setStrategySheetOpen(false);
  };

  const handleSymbolToggle = (symbol: string) => {
    setFormValues((prev) => {
      const symbols = prev.symbols || [];
      if (symbols.includes(symbol)) {
        return { ...prev, symbols: symbols.filter((s) => s !== symbol) };
      }
      return { ...prev, symbols: [...symbols, symbol] };
    });
  };

  const handleDateChange = (type: "start_date" | "end_date", value: string) => {
    setFormValues((prev) => ({ ...prev, [type]: value }));
  };

  const handleIntervalChange = (interval: TimeInterval) => {
    setFormValues((prev) => ({ ...prev, interval }));
  };

  const handleEquityChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value ? parseInt(e.target.value, 10) : 0;
    setFormValues((prev) => ({ ...prev, initial_equity: value }));
  };

  const handleCommissionChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value ? parseFloat(e.target.value) : undefined;
    setFormValues((prev) => ({ ...prev, commission_rate: value }));
  };

  const handleSlippageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value ? parseInt(e.target.value, 10) : undefined;
    setFormValues((prev) => ({ ...prev, slippage_bps: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm(formValues)) {
      submitBacktest(formValues as BacktestFormValues);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  const selectedStrategy = MOCK_STRATEGIES.find((s) => s.id === formValues.strategy_build_id);
  const selectedSymbols = formValues.symbols || [];

  return (
    <form
      onSubmit={handleSubmit}
      className={clsx("flex flex-col gap-6 pb-24", className)}
      noValidate
    >
      {/* Strategy Picker */}
      <div className="flex flex-col gap-2">
        <label htmlFor="strategy-picker" className="block text-sm font-medium text-surface-900">
          Strategy
          <span className="ml-1 text-red-500">*</span>
        </label>
        <button
          id="strategy-picker"
          type="button"
          onClick={() => setStrategySheetOpen(true)}
          className={clsx(
            "flex items-center justify-between rounded-lg border px-4 py-3",
            "transition-colors duration-200",
            getFieldError("strategy_build_id")
              ? "border-red-300 bg-red-50"
              : "border-surface-200 bg-white hover:border-surface-300",
          )}
        >
          <span
            className={clsx(selectedStrategy ? "font-medium text-surface-900" : "text-surface-500")}
          >
            {selectedStrategy?.name || "Select strategy..."}
          </span>
          <ChevronDown className="h-5 w-5 text-surface-400" />
        </button>
        {getFieldError("strategy_build_id") && (
          <p className="text-xs text-red-600" role="alert">
            {getFieldError("strategy_build_id")}
          </p>
        )}
      </div>

      {/* Symbol Picker */}
      <div className="flex flex-col gap-2">
        <label htmlFor="symbol-picker" className="block text-sm font-medium text-surface-900">
          Symbols
          <span className="ml-1 text-red-500">*</span>
        </label>
        <button
          id="symbol-picker"
          type="button"
          onClick={() => setSymbolSheetOpen(true)}
          className={clsx(
            "flex items-center justify-between rounded-lg border px-4 py-3",
            "transition-colors duration-200",
            getFieldError("symbols")
              ? "border-red-300 bg-red-50"
              : "border-surface-200 bg-white hover:border-surface-300",
          )}
        >
          <span className="flex items-center gap-2">
            {selectedSymbols.length > 0 ? (
              <>
                <span className="font-medium text-surface-900">{selectedSymbols.join(", ")}</span>
              </>
            ) : (
              <span className="text-surface-500">Select symbols...</span>
            )}
          </span>
          <ChevronDown className="h-5 w-5 text-surface-400" />
        </button>
        {getFieldError("symbols") && (
          <p className="text-xs text-red-600" role="alert">
            {getFieldError("symbols")}
          </p>
        )}
      </div>

      {/* Date Range */}
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <label htmlFor="start-date" className="block text-sm font-medium text-surface-900">
            Start Date
            <span className="ml-1 text-red-500">*</span>
          </label>
          <input
            id="start-date"
            type="date"
            value={formValues.start_date || ""}
            onChange={(e) => handleDateChange("start_date", e.target.value)}
            className={clsx(
              "rounded-lg border px-4 py-2 font-mono text-sm",
              "transition-colors duration-200",
              getFieldError("start_date")
                ? "border-red-300 bg-red-50"
                : "border-surface-200 bg-white",
            )}
          />
          {getFieldError("start_date") && (
            <p className="text-xs text-red-600" role="alert">
              {getFieldError("start_date")}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="end-date" className="block text-sm font-medium text-surface-900">
            End Date
            <span className="ml-1 text-red-500">*</span>
          </label>
          <input
            id="end-date"
            type="date"
            value={formValues.end_date || ""}
            onChange={(e) => handleDateChange("end_date", e.target.value)}
            className={clsx(
              "rounded-lg border px-4 py-2 font-mono text-sm",
              "transition-colors duration-200",
              getFieldError("end_date")
                ? "border-red-300 bg-red-50"
                : "border-surface-200 bg-white",
            )}
          />
          {getFieldError("end_date") && (
            <p className="text-xs text-red-600" role="alert">
              {getFieldError("end_date")}
            </p>
          )}
        </div>
      </div>

      {/* Time Interval */}
      <div className="flex flex-col gap-2">
        <label htmlFor="interval-control" className="block text-sm font-medium text-surface-900">
          Interval
          <span className="ml-1 text-red-500">*</span>
        </label>
        <SegmentedControl
          id="interval-control"
          options={TIME_INTERVALS}
          value={formValues.interval || "1d"}
          onChange={handleIntervalChange}
        />
        {getFieldError("interval") && (
          <p className="text-xs text-red-600" role="alert">
            {getFieldError("interval")}
          </p>
        )}
      </div>

      {/* Initial Equity */}
      <div className="flex flex-col gap-2">
        <label htmlFor="initial-equity" className="block text-sm font-medium text-surface-900">
          Initial Equity
          <span className="ml-1 text-red-500">*</span>
        </label>
        <div className="flex items-center rounded-lg border px-4 py-2">
          <span className="mr-2 font-medium text-surface-500">$</span>
          <input
            id="initial-equity"
            type="number"
            value={formValues.initial_equity || ""}
            onChange={handleEquityChange}
            min={BACKTEST_CONSTRAINTS.MIN_INITIAL_EQUITY}
            max={BACKTEST_CONSTRAINTS.MAX_INITIAL_EQUITY}
            placeholder="10000"
            className={clsx(
              "flex-1 font-mono text-sm outline-none",
              getFieldError("initial_equity") ? "bg-red-50" : "bg-white",
            )}
          />
        </div>
        <p className="text-xs text-surface-600">
          Min: ${BACKTEST_CONSTRAINTS.MIN_INITIAL_EQUITY} — Max: $
          {BACKTEST_CONSTRAINTS.MAX_INITIAL_EQUITY.toLocaleString()}
        </p>
        {getFieldError("initial_equity") && (
          <p className="text-xs text-red-600" role="alert">
            {getFieldError("initial_equity")}
          </p>
        )}
      </div>

      {/* Advanced Settings Collapsible */}
      <div className="border-t border-surface-200 pt-4">
        <button
          type="button"
          onClick={() => setExpandedAdvanced(!expandedAdvanced)}
          className={clsx(
            "flex w-full items-center justify-between px-0 py-2",
            "text-sm font-medium text-surface-700 hover:text-surface-900",
            "transition-colors duration-200",
          )}
        >
          Advanced Settings
          <ChevronDown
            className={clsx(
              "h-4 w-4 transition-transform duration-200",
              expandedAdvanced ? "rotate-180" : "",
            )}
          />
        </button>

        {expandedAdvanced && (
          <div className="mt-4 flex flex-col gap-4">
            {/* Commission Rate */}
            <div className="flex flex-col gap-2">
              <label htmlFor="commission" className="text-sm font-medium text-surface-900">
                Commission Rate (%)
              </label>
              <input
                id="commission"
                type="number"
                value={
                  formValues.commission_rate !== undefined ? formValues.commission_rate * 100 : ""
                }
                onChange={(e) =>
                  handleCommissionChange({
                    ...e,
                    target: {
                      ...e.target,
                      value: e.target.value ? (parseFloat(e.target.value) / 100).toString() : "",
                    },
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- synthetic-event-rebuild
                  } as any)
                }
                min="0"
                max={BACKTEST_CONSTRAINTS.MAX_COMMISSION_RATE * 100}
                step="0.001"
                placeholder="0"
                className={clsx(
                  "rounded-lg border px-4 py-2 font-mono text-sm",
                  "transition-colors duration-200",
                  getFieldError("commission_rate")
                    ? "border-red-300 bg-red-50"
                    : "border-surface-200 bg-white",
                )}
              />
              {getFieldError("commission_rate") && (
                <p className="text-xs text-red-600" role="alert">
                  {getFieldError("commission_rate")}
                </p>
              )}
            </div>

            {/* Slippage */}
            <div className="flex flex-col gap-2">
              <label htmlFor="slippage" className="text-sm font-medium text-surface-900">
                Slippage (bps)
              </label>
              <input
                id="slippage"
                type="number"
                value={formValues.slippage_bps || ""}
                onChange={handleSlippageChange}
                min="0"
                max={BACKTEST_CONSTRAINTS.MAX_SLIPPAGE_BPS}
                placeholder="0"
                className={clsx(
                  "rounded-lg border px-4 py-2 font-mono text-sm",
                  "transition-colors duration-200",
                  getFieldError("slippage_bps")
                    ? "border-red-300 bg-red-50"
                    : "border-surface-200 bg-white",
                )}
              />
              {getFieldError("slippage_bps") && (
                <p className="text-xs text-red-600" role="alert">
                  {getFieldError("slippage_bps")}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Submit Button - Sticky at bottom */}
      <button
        type="submit"
        disabled={!isFormValid || isSubmitting}
        className={clsx(
          "fixed bottom-0 left-0 right-0 px-4 py-4 font-semibold",
          "transition-colors duration-200",
          isFormValid && !isSubmitting
            ? "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800"
            : "cursor-not-allowed bg-surface-200 text-surface-500",
        )}
      >
        {isSubmitting ? "Submitting..." : "Run Backtest"}
      </button>

      {/* Strategy Picker Bottom Sheet */}
      <BottomSheet
        isOpen={strategySheetOpen}
        onClose={() => setStrategySheetOpen(false)}
        title="Select Strategy"
      >
        <div className="flex flex-col gap-2">
          {MOCK_STRATEGIES.map((strategy) => (
            <button
              key={strategy.id}
              type="button"
              onClick={() => handleStrategySelect(strategy.id)}
              className={clsx(
                "w-full rounded-lg px-4 py-3 text-left",
                "transition-colors duration-200",
                formValues.strategy_build_id === strategy.id
                  ? "bg-brand-100 font-medium text-brand-700"
                  : "bg-surface-50 text-surface-900 hover:bg-surface-100",
              )}
            >
              {strategy.name}
            </button>
          ))}
        </div>
      </BottomSheet>

      {/* Symbol Picker Bottom Sheet */}
      <BottomSheet
        isOpen={symbolSheetOpen}
        onClose={() => setSymbolSheetOpen(false)}
        title="Select Symbols"
      >
        <div className="flex flex-col gap-3">
          {/* Search */}
          <input
            type="text"
            placeholder="Search symbols..."
            value={symbolSearch}
            onChange={(e) => setSymbolSearch(e.target.value)}
            className="rounded-lg border border-surface-200 px-4 py-2 text-sm"
          />

          {/* Symbol Grid */}
          <div className="grid grid-cols-3 gap-2">
            {filteredSymbols.map((symbol) => (
              <button
                key={symbol}
                type="button"
                onClick={() => handleSymbolToggle(symbol)}
                className={clsx(
                  "rounded-lg px-3 py-2 text-sm font-medium",
                  "transition-colors duration-200",
                  selectedSymbols.includes(symbol)
                    ? "bg-brand-600 text-white"
                    : "bg-surface-100 text-surface-700 hover:bg-surface-200",
                )}
              >
                {symbol}
              </button>
            ))}
          </div>

          {/* Done Button */}
          <button
            type="button"
            onClick={() => setSymbolSheetOpen(false)}
            className="mt-4 w-full rounded-lg bg-brand-600 py-3 font-medium text-white hover:bg-brand-700"
          >
            Done
          </button>
        </div>
      </BottomSheet>
    </form>
  );
}
