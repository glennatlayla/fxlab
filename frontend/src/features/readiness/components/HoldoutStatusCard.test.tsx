/**
 * Tests for HoldoutStatusCard component.
 *
 * Verifies holdout pass/fail, dates, and contamination flag rendering.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HoldoutStatusCard } from "./HoldoutStatusCard";
import type { HoldoutEvaluation } from "@/types/readiness";

function makeHoldout(overrides?: Partial<HoldoutEvaluation>): HoldoutEvaluation {
  return {
    evaluated: true,
    passed: true,
    start_date: "2025-06-01T00:00:00Z",
    end_date: "2025-12-31T00:00:00Z",
    contamination_detected: false,
    sharpe_ratio: 1.25,
    ...overrides,
  };
}

describe("HoldoutStatusCard", () => {
  it("renders the holdout card", () => {
    render(<HoldoutStatusCard holdout={makeHoldout()} />);
    expect(screen.getByTestId("holdout-status-card")).toBeInTheDocument();
  });

  it("shows pass state for passing holdout", () => {
    render(<HoldoutStatusCard holdout={makeHoldout()} />);
    expect(screen.getByText(/pass/i)).toBeInTheDocument();
  });

  it("shows fail state for failing holdout", () => {
    render(<HoldoutStatusCard holdout={makeHoldout({ passed: false, sharpe_ratio: -0.3 })} />);
    expect(screen.getByText(/fail/i)).toBeInTheDocument();
  });

  it("displays holdout period dates", () => {
    render(<HoldoutStatusCard holdout={makeHoldout()} />);
    expect(screen.getByTestId("holdout-dates")).toBeInTheDocument();
  });

  it("shows contamination warning when detected", () => {
    render(<HoldoutStatusCard holdout={makeHoldout({ contamination_detected: true })} />);
    expect(screen.getByText(/contamination/i)).toBeInTheDocument();
  });

  it("hides contamination warning when clean", () => {
    render(<HoldoutStatusCard holdout={makeHoldout({ contamination_detected: false })} />);
    expect(screen.queryByText(/contamination/i)).not.toBeInTheDocument();
  });

  it("displays Sharpe ratio", () => {
    render(<HoldoutStatusCard holdout={makeHoldout()} />);
    expect(screen.getByText("1.25")).toBeInTheDocument();
  });

  it("shows not-evaluated state", () => {
    render(
      <HoldoutStatusCard
        holdout={makeHoldout({ evaluated: false, passed: false, sharpe_ratio: null })}
      />,
    );
    expect(screen.getByText(/not evaluated/i)).toBeInTheDocument();
  });
});
