/**
 * ReadinessViewer — overall grade, score, and policy version display.
 *
 * Purpose:
 *   Render the top-level readiness assessment summary including the
 *   grade badge, overall score, policy version, and interpretation text.
 *
 * Responsibilities:
 *   - Display grade badge prominently.
 *   - Show overall numeric score.
 *   - Display policy version used for assessment.
 *   - Show grade interpretation text.
 *   - Show assessment timestamp and assessor.
 *
 * Does NOT:
 *   - Fetch data (parent provides all props).
 *   - Render scoring dimensions or blockers.
 *
 * Dependencies:
 *   - GradeBadge component.
 *   - GRADE_INTERPRETATION from ../constants.
 *
 * Example:
 *   <ReadinessViewer grade="B" score={72} policyVersion="1" assessedAt="..." assessor="..." />
 */

import { memo } from "react";
import type { ReadinessViewerProps } from "../types";
import { GradeBadge } from "./GradeBadge";
import { GRADE_INTERPRETATION } from "../constants";

/**
 * Render the readiness assessment summary.
 *
 * Args:
 *   grade: Overall grade (A-F).
 *   score: Numeric score (0-100).
 *   policyVersion: Policy version string.
 *   assessedAt: ISO-8601 timestamp.
 *   assessor: Who/what performed the assessment.
 *
 * Returns:
 *   Summary card with grade badge and metadata.
 */
export const ReadinessViewer = memo(function ReadinessViewer({
  grade,
  score,
  policyVersion,
  assessedAt,
  assessor,
}: ReadinessViewerProps) {
  return (
    <div data-testid="readiness-viewer" className="rounded-lg border border-slate-200 bg-white p-6">
      <div className="flex items-center gap-6">
        <GradeBadge grade={grade} size="lg" />
        <div className="flex-1">
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold text-slate-900">{score}</span>
            <span className="text-sm text-slate-500">/ 100</span>
          </div>
          <p className="mt-1 text-sm text-slate-600">{GRADE_INTERPRETATION[grade]}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-500">
        <span>Policy v{policyVersion}</span>
        <span data-testid="readiness-assessed-at">
          Assessed: {new Date(assessedAt).toLocaleString()}
        </span>
        <span>By: {assessor}</span>
      </div>
    </div>
  );
});
