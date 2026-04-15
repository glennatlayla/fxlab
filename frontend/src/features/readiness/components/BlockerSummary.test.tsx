/**
 * Tests for BlockerSummary component.
 *
 * AC-5: BlockerSummary for a failing dimension includes owner display name
 * and next-step button.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BlockerSummary } from "./BlockerSummary";
import type { ReadinessBlocker } from "@/types/readiness";

function makeBlockers(): ReadinessBlocker[] {
  return [
    {
      code: "HOLDOUT_FAIL",
      message: "Holdout evaluation Sharpe is negative",
      blocker_owner: "Quantitative Research",
      next_step: "Re-evaluate holdout period or adjust strategy parameters",
      severity: "critical",
    },
    {
      code: "DRAWDOWN_EXCESSIVE",
      message: "Maximum drawdown exceeds 40% threshold",
      blocker_owner: "Risk Management",
      next_step: "Implement position sizing constraints",
      severity: "high",
    },
  ];
}

describe("BlockerSummary", () => {
  it("renders a card for each blocker", () => {
    render(<BlockerSummary blockers={makeBlockers()} />);
    expect(screen.getByText("HOLDOUT_FAIL")).toBeInTheDocument();
    expect(screen.getByText("DRAWDOWN_EXCESSIVE")).toBeInTheDocument();
  });

  it("displays blocker owner display name", () => {
    render(<BlockerSummary blockers={makeBlockers()} />);
    expect(screen.getByText("Quantitative Research")).toBeInTheDocument();
    expect(screen.getByText("Risk Management")).toBeInTheDocument();
  });

  it("displays human-readable blocker message", () => {
    render(<BlockerSummary blockers={makeBlockers()} />);
    expect(screen.getByText("Holdout evaluation Sharpe is negative")).toBeInTheDocument();
  });

  it("displays next-step action for each blocker", () => {
    render(<BlockerSummary blockers={makeBlockers()} />);
    expect(
      screen.getByText("Re-evaluate holdout period or adjust strategy parameters"),
    ).toBeInTheDocument();
  });

  it("renders severity badges", () => {
    render(<BlockerSummary blockers={makeBlockers()} />);
    const cards = screen.getAllByTestId(/^blocker-card-/);
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute("data-severity", "critical");
    expect(cards[1]).toHaveAttribute("data-severity", "high");
  });

  it("renders empty state for no blockers", () => {
    render(<BlockerSummary blockers={[]} />);
    expect(screen.getByTestId("blocker-summary-empty")).toBeInTheDocument();
  });
});
