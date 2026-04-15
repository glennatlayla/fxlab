/**
 * PromotionButton — submit for promotion with rationale collection, absent for grade F.
 *
 * Purpose:
 *   Render a promotion submission workflow that collects a rationale and
 *   target stage before submitting. Completely absent when grade is F
 *   (not merely disabled). Disabled when a pending promotion exists
 *   or submission is in progress.
 *
 * Responsibilities:
 *   - Return null (render nothing) for grade F — AC-3.
 *   - Disable when pending promotion exists.
 *   - Disable during submission.
 *   - Show pending label when promotion is pending.
 *   - Expand inline form on "Submit for Promotion" click.
 *   - Validate rationale is non-empty before enabling confirm.
 *   - Collect target stage (paper | live) via select dropdown.
 *   - Allow cancelling the form without submitting.
 *
 * Does NOT:
 *   - Execute the promotion (parent handles via onSubmit callback).
 *   - Determine the grade (parent provides it).
 *
 * Dependencies:
 *   - PromotionButtonProps from ../types.
 *
 * Example:
 *   <PromotionButton grade="B" hasPendingPromotion={false} runId="..." onSubmit={fn} />
 */

import { memo, useState, useCallback } from "react";
import type { PromotionButtonProps } from "../types";

/** Valid target stages for promotion requests. */
const TARGET_STAGES = [
  { value: "paper", label: "Paper Trading" },
  { value: "live", label: "Live Trading" },
] as const;

/** Minimum rationale length to enable submission. */
const MIN_RATIONALE_LENGTH = 10;

/**
 * Render the promotion button with rationale form, or null for grade F.
 *
 * Args:
 *   grade: Current readiness grade.
 *   hasPendingPromotion: Whether a pending promotion exists.
 *   runId: Run ID (for context).
 *   onSubmit: Callback with (rationale, targetStage).
 *   isSubmitting: Whether submission is in progress.
 *
 * Returns:
 *   Button element (with optional expanded form) or null (for grade F).
 */
export const PromotionButton = memo(function PromotionButton({
  grade,
  hasPendingPromotion,
  runId: _runId,
  onSubmit,
  isSubmitting = false,
}: PromotionButtonProps) {
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [rationale, setRationale] = useState("");
  const [targetStage, setTargetStage] = useState<string>("paper");

  const handleOpenForm = useCallback(() => {
    setIsFormOpen(true);
  }, []);

  const handleCancel = useCallback(() => {
    setIsFormOpen(false);
    setRationale("");
    setTargetStage("paper");
  }, []);

  const handleConfirm = useCallback(() => {
    onSubmit(rationale.trim(), targetStage);
    // Keep form open during submission; parent controls isSubmitting.
    // Reset form on next open (via handleCancel or parent re-render on success).
  }, [rationale, targetStage, onSubmit]);

  // AC-3: "Submit for promotion" is absent (not merely disabled) when grade is F.
  if (grade === "F") {
    return null;
  }

  const isDisabled = hasPendingPromotion || isSubmitting;
  const isRationaleValid = rationale.trim().length >= MIN_RATIONALE_LENGTH;

  // Expanded form: rationale + target stage + confirm/cancel.
  if (isFormOpen && !hasPendingPromotion) {
    return (
      <div data-testid="promotion-button-container" className="space-y-3">
        <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <label htmlFor="promotion-rationale" className="block text-sm font-medium text-slate-700">
            Promotion Rationale
          </label>
          <textarea
            id="promotion-rationale"
            data-testid="promotion-rationale-input"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            disabled={isSubmitting}
            placeholder="Describe why this strategy is ready for promotion (min 10 characters)..."
            rows={3}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
            aria-describedby="rationale-hint"
          />
          <p id="rationale-hint" className="text-xs text-slate-500">
            {rationale.trim().length}/{MIN_RATIONALE_LENGTH} characters minimum
          </p>

          <div>
            <label
              htmlFor="promotion-target-stage"
              className="block text-sm font-medium text-slate-700"
            >
              Target Stage
            </label>
            <select
              id="promotion-target-stage"
              data-testid="promotion-target-stage-select"
              value={targetStage}
              onChange={(e) => setTargetStage(e.target.value)}
              disabled={isSubmitting}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
            >
              {TARGET_STAGES.map((stage) => (
                <option key={stage.value} value={stage.value}>
                  {stage.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!isRationaleValid || isSubmitting}
              onClick={handleConfirm}
              data-testid="promotion-confirm-button"
              className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Confirm promotion submission"
            >
              {isSubmitting ? (
                <>
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" aria-hidden="true">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                  Submitting...
                </>
              ) : (
                "Confirm Submission"
              )}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              disabled={isSubmitting}
              data-testid="promotion-cancel-button"
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Collapsed state: single trigger button.
  return (
    <div data-testid="promotion-button-container">
      <button
        type="button"
        disabled={isDisabled}
        onClick={handleOpenForm}
        className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
        aria-label="Submit for promotion"
      >
        {hasPendingPromotion ? "Promotion Pending" : "Submit for Promotion"}
      </button>
    </div>
  );
});
