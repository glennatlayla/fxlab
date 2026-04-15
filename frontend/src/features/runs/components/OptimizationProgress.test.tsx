/**
 * Tests for OptimizationProgress component.
 *
 * Verifies trial gauge, best trial display, and throughput metrics.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OptimizationProgress } from "./OptimizationProgress";
import type { OptimizationMetrics } from "@/types/run";

function makeMetrics(overrides: Partial<OptimizationMetrics> = {}): OptimizationMetrics {
  return {
    totalTrials: 100,
    completedTrials: 42,
    bestObjectiveValue: 1.5678,
    bestTrialIndex: 37,
    trialsPerMinute: 8.3,
    ...overrides,
  };
}

describe("OptimizationProgress", () => {
  it("renders trial count", () => {
    render(<OptimizationProgress metrics={makeMetrics()} status="running" />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("/ 100")).toBeInTheDocument();
  });

  it("renders best objective value", () => {
    render(<OptimizationProgress metrics={makeMetrics()} status="running" />);
    expect(screen.getByText("1.5678")).toBeInTheDocument();
  });

  it("renders best trial index", () => {
    render(<OptimizationProgress metrics={makeMetrics()} status="running" />);
    expect(screen.getByText(/Trial #37/)).toBeInTheDocument();
  });

  it("renders trials per minute", () => {
    render(<OptimizationProgress metrics={makeMetrics()} status="running" />);
    expect(screen.getByText("8.3")).toBeInTheDocument();
  });

  it("shows dash when no best objective", () => {
    render(
      <OptimizationProgress
        metrics={makeMetrics({ bestObjectiveValue: null, bestTrialIndex: null })}
        status="running"
      />,
    );
    // Should show "—" instead of a number
    const dashElements = screen.getAllByText("—");
    expect(dashElements.length).toBeGreaterThan(0);
  });

  it("renders progressbar with correct aria attributes", () => {
    render(<OptimizationProgress metrics={makeMetrics()} status="running" />);
    const progressbar = screen.getByRole("progressbar");
    expect(progressbar.getAttribute("aria-valuenow")).toBe("42");
  });
});
