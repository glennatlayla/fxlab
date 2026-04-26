/**
 * Tests for TrialEstimator component (FE-15).
 *
 * Spec: Visual trial count indicator with color coding
 * - Shows estimated trial count
 * - Color codes by severity: green < 100, amber 100-1000, orange 1000-10000, red > 10000
 * - Updates reactively on parameter change
 * - Shows estimated duration (if benchmarks available)
 * - Shows warning message for extreme counts
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { TrialEstimator } from "../TrialEstimator";
import type { ParameterRange } from "../../optimisation";

describe("TrialEstimator", () => {
  describe("rendering", () => {
    it("renders_trial_count", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 5, max: 20, step: 5 }];

      render(<TrialEstimator parameters={params} />);

      // ceil((20 - 5) / 5) + 1 = 4 combinations
      expect(screen.getByText("4")).toBeInTheDocument();
    });

    it("renders_count_and_badge", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 5, max: 20, step: 5 }];

      render(<TrialEstimator parameters={params} />);

      expect(screen.getByText(/estimated trials/i)).toBeInTheDocument();
      expect(screen.getByText(/fast/i)).toBeInTheDocument(); // severity badge
    });
  });

  describe("color coding", () => {
    it("shows_green_for_low_count", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 5, step: 1 }];

      render(<TrialEstimator parameters={params} />);

      const badge = screen.getByText(/fast/i);
      expect(badge).toHaveClass("bg-green-500");
    });

    it("shows_amber_for_moderate_count", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 101, step: 1 }];
      // 101 - 1 / 1 + 1 = 101 combinations (moderate: 100-999)

      render(<TrialEstimator parameters={params} />);

      const badge = screen.getByText(/moderate/i);
      expect(badge).toHaveClass("bg-amber-500");
    });

    it("shows_orange_for_high_count", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 1001, step: 1 }];
      // 1001 - 1 / 1 + 1 = 1001 combinations (high: 1000-9999)

      render(<TrialEstimator parameters={params} />);

      const badge = screen.getByText(/long/i);
      expect(badge).toHaveClass("bg-orange-500");
    });

    it("shows_red_for_extreme_count", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 10001, step: 1 }];
      // 10001 - 1 / 1 + 1 = 10001 combinations (extreme: 10000+)

      render(<TrialEstimator parameters={params} />);

      const badge = screen.getByText(/very long/i);
      expect(badge).toHaveClass("bg-red-500");
    });
  });

  describe("updates", () => {
    it("updates_on_parameter_change", async () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 10, step: 1 }];

      const { rerender } = render(<TrialEstimator parameters={params} />);

      expect(screen.getByText("10")).toBeInTheDocument();

      // Update parameters to create more combinations
      const newParams: ParameterRange[] = [{ name: "fast", min: 1, max: 20, step: 1 }];

      rerender(<TrialEstimator parameters={newParams} />);

      await waitFor(() => {
        expect(screen.getByText("20")).toBeInTheDocument();
      });
    });

    it("handles_multiple_parameters", () => {
      const params: ParameterRange[] = [
        { name: "fast", min: 1, max: 5, step: 1 },
        { name: "slow", min: 1, max: 3, step: 1 },
      ];

      render(<TrialEstimator parameters={params} />);

      // 5 × 3 = 15 total combinations
      expect(screen.getByText("15")).toBeInTheDocument();
    });
  });

  describe("extreme count warning", () => {
    it("shows_warning_for_count_over_10000", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 10001, step: 1 }];
      // 10001 - 1 / 1 + 1 = 10001 combinations (exceeds soft limit of 10000)

      render(<TrialEstimator parameters={params} />);

      expect(screen.getByText(/may take considerable time/i)).toBeInTheDocument();
    });

    it("hides_warning_for_count_under_10000", () => {
      const params: ParameterRange[] = [{ name: "fast", min: 1, max: 100, step: 1 }];

      render(<TrialEstimator parameters={params} />);

      expect(screen.queryByText(/consider reducing parameters/i)).not.toBeInTheDocument();
    });
  });

  describe("edge cases", () => {
    it("handles_empty_parameters", () => {
      render(<TrialEstimator parameters={[]} />);

      expect(screen.getByText(/add parameters to estimate trial count/i)).toBeInTheDocument();
    });

    it("handles_fractional_step_sizes", () => {
      const params: ParameterRange[] = [{ name: "threshold", min: 0.1, max: 0.9, step: 0.1 }];

      render(<TrialEstimator parameters={params} />);

      // ceil((0.9 - 0.1) / 0.1) + 1 = 9
      expect(screen.getByText("9")).toBeInTheDocument();
    });
  });
});
