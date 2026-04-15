/**
 * Tests for CandidateComparisonTable component.
 *
 * Verifies side-by-side comparison rendering of candidate metrics,
 * download callback, empty state, column headers with ARIA roles,
 * and virtual scroll container sizing.
 *
 * Note: TanStack Virtual requires a real layout engine for visible-row
 * rendering. In jsdom (no layout), getVirtualItems() returns empty.
 * We verify the virtualizer is wired by checking the inner container's
 * computed total height (candidateCount * CANDIDATE_TABLE_ROW_HEIGHT).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CandidateComparisonTable } from "./CandidateComparisonTable";
import type { CandidateMetrics } from "@/types/results";
import { CANDIDATE_TABLE_ROW_HEIGHT, CANDIDATE_TABLE_VIEWPORT_HEIGHT } from "../constants";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCandidates(count: number): CandidateMetrics[] {
  return Array.from({ length: count }, (_, i) => ({
    candidate_id: `01HCAND${String(i).padStart(19, "0")}`,
    label: `Candidate ${i + 1}`,
    objective_value: 1.8 - i * 0.1,
    sharpe_ratio: 1.8 - i * 0.1,
    max_drawdown_pct: -10 - i * 2,
    total_return_pct: 40 - i * 5,
    win_rate: 0.6 - i * 0.05,
    profit_factor: 1.8 - i * 0.2,
    trade_count: 120 + i * 10,
  }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CandidateComparisonTable", () => {
  // -------------------------------------------------------------------------
  // Basic rendering
  // -------------------------------------------------------------------------

  it("renders the candidate comparison table container", () => {
    render(<CandidateComparisonTable candidates={makeCandidates(3)} onDownload={vi.fn()} />);
    expect(screen.getByTestId("candidate-comparison-table")).toBeInTheDocument();
  });

  it("displays key metric column headers", () => {
    render(<CandidateComparisonTable candidates={makeCandidates(2)} onDownload={vi.fn()} />);
    expect(screen.getByText("Sharpe")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("Profit Factor")).toBeInTheDocument();
  });

  it("displays candidate count in header", () => {
    render(<CandidateComparisonTable candidates={makeCandidates(5)} onDownload={vi.fn()} />);
    expect(screen.getByText("Candidates (5)")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // ARIA roles on column headers
  // -------------------------------------------------------------------------

  it("column headers have ARIA columnheader role", () => {
    render(<CandidateComparisonTable candidates={makeCandidates(2)} onDownload={vi.fn()} />);
    const headers = screen.getAllByRole("columnheader");
    expect(headers.length).toBe(8);
    const headerTexts = headers.map((h) => h.textContent);
    expect(headerTexts).toContain("Label");
    expect(headerTexts).toContain("Objective");
    expect(headerTexts).toContain("Sharpe");
    expect(headerTexts).toContain("Trades");
  });

  // -------------------------------------------------------------------------
  // Download
  // -------------------------------------------------------------------------

  it("calls onDownload when download button is clicked", async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();
    render(<CandidateComparisonTable candidates={makeCandidates(2)} onDownload={onDownload} />);
    const btn = screen.getByRole("button", { name: /download/i });
    await user.click(btn);
    expect(onDownload).toHaveBeenCalledOnce();
  });

  it("disables download button when isDownloading is true", () => {
    render(
      <CandidateComparisonTable
        candidates={makeCandidates(2)}
        onDownload={vi.fn()}
        isDownloading={true}
      />,
    );
    const btn = screen.getByRole("button", { name: /download/i });
    expect(btn).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // Empty state
  // -------------------------------------------------------------------------

  it("renders empty state when no candidates provided", () => {
    render(<CandidateComparisonTable candidates={[]} onDownload={vi.fn()} />);
    expect(screen.getByTestId("candidate-comparison-empty")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Virtual scroll container sizing
  // -------------------------------------------------------------------------

  it("scroll container has correct viewport height", () => {
    render(<CandidateComparisonTable candidates={makeCandidates(5)} onDownload={vi.fn()} />);
    const table = screen.getByTestId("candidate-comparison-table");
    const scrollContainer = table.querySelector(".overflow-auto") as HTMLElement;
    expect(scrollContainer).not.toBeNull();
    expect(scrollContainer.style.height).toBe(`${CANDIDATE_TABLE_VIEWPORT_HEIGHT}px`);
  });

  it("inner virtual container total size matches candidateCount * rowHeight", () => {
    const count = 20;
    render(<CandidateComparisonTable candidates={makeCandidates(count)} onDownload={vi.fn()} />);
    const table = screen.getByTestId("candidate-comparison-table");
    const scrollContainer = table.querySelector(".overflow-auto") as HTMLElement;
    const innerDiv = scrollContainer.firstElementChild as HTMLElement;
    const expectedHeight = count * CANDIDATE_TABLE_ROW_HEIGHT;
    expect(innerDiv.style.height).toBe(`${expectedHeight}px`);
  });

  it("uses relative positioning for virtual row container", () => {
    render(<CandidateComparisonTable candidates={makeCandidates(5)} onDownload={vi.fn()} />);
    const table = screen.getByTestId("candidate-comparison-table");
    const scrollContainer = table.querySelector(".overflow-auto") as HTMLElement;
    const innerDiv = scrollContainer.firstElementChild as HTMLElement;
    expect(innerDiv.style.position).toBe("relative");
  });
});
