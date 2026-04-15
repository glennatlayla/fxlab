/**
 * GradeBadge — color-coded readiness grade display (A through F).
 *
 * Purpose:
 *   Render a readiness grade as a prominent badge with color mapping
 *   per Phase 2 §8.4 scoring methodology.
 *
 * Responsibilities:
 *   - Display grade letter with appropriate color class.
 *   - Support size variants (sm, md, lg) for different contexts.
 *
 * Does NOT:
 *   - Compute the grade (backend-authoritative).
 *   - Contain any fetch logic.
 *
 * Dependencies:
 *   - GRADE_BADGE_CLASSES from ../constants.
 *
 * Example:
 *   <GradeBadge grade="A" size="lg" />
 */

import { memo } from "react";
import type { GradeBadgeProps } from "../types";
import { GRADE_BADGE_CLASSES } from "../constants";

const SIZE_CLASSES = {
  sm: "h-8 w-8 text-sm font-bold",
  md: "h-12 w-12 text-xl font-bold",
  lg: "h-16 w-16 text-3xl font-extrabold",
} as const;

/**
 * Render a color-coded grade badge.
 *
 * Args:
 *   grade: Readiness grade (A-F).
 *   size: Size variant (default "md").
 *
 * Returns:
 *   Badge element with grade letter and color styling.
 */
export const GradeBadge = memo(function GradeBadge({ grade, size = "md" }: GradeBadgeProps) {
  return (
    <span
      data-testid="grade-badge"
      className={`inline-flex items-center justify-center rounded-full ring-1 ring-inset ${GRADE_BADGE_CLASSES[grade]} ${SIZE_CLASSES[size]}`}
    >
      {grade}
    </span>
  );
});
