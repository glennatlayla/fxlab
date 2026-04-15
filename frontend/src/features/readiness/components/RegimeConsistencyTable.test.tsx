/**
 * Tests for RegimeConsistencyTable component.
 *
 * Verifies per-regime Sharpe display with pass/fail indicators.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RegimeConsistencyTable } from "./RegimeConsistencyTable";
import type { RegimeConsistencyEntry } from "@/types/readiness";

function makeEntries(): RegimeConsistencyEntry[] {
  return [
    { regime: "bull", sharpe_ratio: 1.85, passed: true, trade_count: 45 },
    { regime: "bear", sharpe_ratio: 0.42, passed: true, trade_count: 32 },
    { regime: "sideways", sharpe_ratio: -0.15, passed: false, trade_count: 28 },
  ];
}

describe("RegimeConsistencyTable", () => {
  it("renders a row for each regime", () => {
    render(<RegimeConsistencyTable entries={makeEntries()} />);
    expect(screen.getByText("bull")).toBeInTheDocument();
    expect(screen.getByText("bear")).toBeInTheDocument();
    expect(screen.getByText("sideways")).toBeInTheDocument();
  });

  it("displays Sharpe ratios", () => {
    render(<RegimeConsistencyTable entries={makeEntries()} />);
    expect(screen.getByText("1.85")).toBeInTheDocument();
    expect(screen.getByText("0.42")).toBeInTheDocument();
    expect(screen.getByText("-0.15")).toBeInTheDocument();
  });

  it("shows pass/fail indicators", () => {
    render(<RegimeConsistencyTable entries={makeEntries()} />);
    const rows = screen.getAllByTestId(/^regime-row-/);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveAttribute("data-passed", "true");
    expect(rows[2]).toHaveAttribute("data-passed", "false");
  });

  it("displays trade count per regime", () => {
    render(<RegimeConsistencyTable entries={makeEntries()} />);
    expect(screen.getByText("45")).toBeInTheDocument();
    expect(screen.getByText("32")).toBeInTheDocument();
  });

  it("renders empty state for no entries", () => {
    render(<RegimeConsistencyTable entries={[]} />);
    expect(screen.getByTestId("regime-consistency-empty")).toBeInTheDocument();
  });

  it("includes an accessible table caption for screen readers", () => {
    render(<RegimeConsistencyTable entries={makeEntries()} />);
    const caption = document.querySelector("caption");
    expect(caption).not.toBeNull();
    expect(caption?.className).toContain("sr-only");
  });

  it("formats Sharpe ratios to two decimal places", () => {
    // 0.4 should render as "0.40", not "0.4"
    const entries = [{ regime: "test", sharpe_ratio: 0.4, passed: true, trade_count: 10 }];
    render(<RegimeConsistencyTable entries={entries} />);
    expect(screen.getByText("0.40")).toBeInTheDocument();
  });
});
