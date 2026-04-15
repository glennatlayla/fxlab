/**
 * Tests for ScoringBreakdown component.
 *
 * Verifies per-dimension sub-score cards with threshold and pass/fail.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoringBreakdown } from "./ScoringBreakdown";
import type { ScoringDimension } from "@/types/readiness";

function makeDimensions(): ScoringDimension[] {
  return [
    {
      dimension: "oos_stability",
      label: "OOS Stability",
      score: 85,
      weight: 0.2,
      threshold: 35,
      passed: true,
      details: "OOS/IS ratio: 0.78",
    },
    {
      dimension: "drawdown",
      label: "Max Drawdown",
      score: 25,
      weight: 0.2,
      threshold: 35,
      passed: false,
      details: "Max DD: 45% of capital",
    },
    {
      dimension: "trade_count",
      label: "Trade Count",
      score: 90,
      weight: 0.15,
      threshold: 35,
      passed: true,
      details: "128 OOS trades",
    },
  ];
}

describe("ScoringBreakdown", () => {
  it("renders a card for each dimension", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    expect(screen.getByText("OOS Stability")).toBeInTheDocument();
    expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
    expect(screen.getByText("Trade Count")).toBeInTheDocument();
  });

  it("renders correct number of dimension cards", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    const cards = screen.getAllByTestId(/^dimension-card-/);
    expect(cards.length).toBe(3);
  });

  it("marks failing dimension with data-passed=false", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    const failCard = screen.getByTestId("dimension-card-drawdown");
    expect(failCard).toHaveAttribute("data-passed", "false");
  });

  it("marks passing dimension with data-passed=true", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    const passCard = screen.getByTestId("dimension-card-oos_stability");
    expect(passCard).toHaveAttribute("data-passed", "true");
  });

  it("renders progress bars with ARIA attributes", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    const progressBars = screen.getAllByRole("progressbar");
    expect(progressBars.length).toBe(3);
    // First dimension (OOS Stability, score 85) should have correct ARIA
    const oosBar = screen.getByRole("progressbar", { name: "OOS Stability score" });
    expect(oosBar).toHaveAttribute("aria-valuenow", "85");
    expect(oosBar).toHaveAttribute("aria-valuemin", "0");
    expect(oosBar).toHaveAttribute("aria-valuemax", "100");
  });

  it("displays dimension score values", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    expect(screen.getByText("85")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
  });

  it("displays details when provided", () => {
    render(<ScoringBreakdown dimensions={makeDimensions()} />);
    expect(screen.getByText("OOS/IS ratio: 0.78")).toBeInTheDocument();
  });

  it("renders empty state for no dimensions", () => {
    render(<ScoringBreakdown dimensions={[]} />);
    expect(screen.getByTestId("scoring-breakdown-empty")).toBeInTheDocument();
  });
});
