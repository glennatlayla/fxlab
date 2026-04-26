/**
 * PaperTradingReview — Configuration review and confirmation card.
 *
 * Purpose:
 *   Display a formatted summary of paper trading configuration for user review.
 *   Require explicit confirmation via SlideToConfirm gesture before submission.
 *
 * Responsibilities:
 *   - Format and display all configuration fields.
 *   - Show currency values with proper formatting (e.g., "$10,000.00").
 *   - Show leverage as multiplier (e.g., "2.5x").
 *   - Render SlideToConfirm for explicit user confirmation.
 *   - Display loading state while submitting.
 *   - Display error messages if submission fails.
 *
 * Does NOT:
 *   - Make API calls (parent component responsible).
 *   - Execute business logic.
 *   - Manage state.
 *
 * Dependencies:
 *   - React.
 *   - SlideToConfirm component.
 *   - PaperTradingReviewSummary type.
 *
 * Error conditions:
 *   - API errors: displayed via error prop.
 *   - Network errors: handled by parent.
 *
 * Example:
 *   <PaperTradingReview
 *     summary={reviewSummary}
 *     isSubmitting={false}
 *     onConfirm={handleConfirm}
 *   />
 */

import React from "react";
import { SlideToConfirm } from "@/components/mobile/SlideToConfirm";
import type { PaperTradingReviewSummary } from "../types";

export interface PaperTradingReviewProps {
  /** Summary of configuration to display for review. */
  summary: PaperTradingReviewSummary;
  /** Whether submission is in progress. */
  isSubmitting: boolean;
  /** Callback when slide confirmation completes. */
  onConfirm: () => void;
  /** Optional error message to display. */
  error?: string | null;
}

/**
 * PaperTradingReview component.
 *
 * Displays a formatted review card with all paper trading configuration.
 * Requires user to slide to confirm submission.
 *
 * Example:
 *   <PaperTradingReview
 *     summary={summary}
 *     isSubmitting={isSubmitting}
 *     onConfirm={handleConfirm}
 *   />
 */
export function PaperTradingReview({
  summary,
  isSubmitting,
  onConfirm,
  error,
}: PaperTradingReviewProps): React.ReactElement {
  return (
    <div className="flex flex-col gap-6 p-4">
      {/* Error banner */}
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Review card */}
      <div className="rounded-lg border border-surface-200 bg-surface-50 p-6">
        <h2 className="mb-6 text-xl font-semibold text-surface-900">Review Configuration</h2>

        {/* Configuration details grid */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* Deployment */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Deployment
            </label>
            <p className="text-base font-medium text-surface-900">{summary.deploymentName}</p>
          </div>

          {/* Strategy */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Strategy
            </label>
            <p className="text-base font-medium text-surface-900">{summary.strategyName}</p>
          </div>

          {/* Initial Equity */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Initial Equity
            </label>
            <p className="text-base font-medium text-surface-900">{summary.initialEquityDisplay}</p>
          </div>

          {/* Max Position Size */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Max Position Size
            </label>
            <p className="text-base font-medium text-surface-900">
              {summary.maxPositionSizeDisplay}
            </p>
          </div>

          {/* Max Daily Loss */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Max Daily Loss
            </label>
            <p className="text-base font-medium text-surface-900">{summary.maxDailyLossDisplay}</p>
          </div>

          {/* Max Leverage */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Max Leverage
            </label>
            <p className="text-base font-medium text-surface-900">{summary.maxLeverageDisplay}</p>
          </div>

          {/* Trading Symbols */}
          <div className="md:col-span-2">
            <label className="mb-1 block text-xs font-medium uppercase text-surface-500">
              Trading Symbols
            </label>
            <p className="text-base font-medium text-surface-900">{summary.symbolsDisplay}</p>
          </div>
        </div>
      </div>

      {/* Confirmation section */}
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4">
        <p className="mb-4 text-sm text-yellow-800">
          Paper trading uses simulated market data. Ensure all configuration matches your strategy
          requirements before confirming.
        </p>

        <SlideToConfirm
          label="Slide to start paper trading"
          onConfirm={onConfirm}
          variant="default"
          disabled={isSubmitting}
        />

        {isSubmitting && (
          <p className="mt-3 text-center text-sm text-surface-600">
            Starting paper trading deployment...
          </p>
        )}
      </div>
    </div>
  );
}
