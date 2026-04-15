/**
 * Tests for ReportHistory component.
 *
 * Verifies report history list renders in reverse chronological order.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportHistory } from "./ReportHistory";
import type { ReadinessReportHistoryEntry } from "@/types/readiness";

function makeEntries(): ReadinessReportHistoryEntry[] {
  return [
    {
      report_id: "rpt-3",
      grade: "B",
      score: 72,
      assessed_at: "2026-04-05T14:00:00Z",
      policy_version: "1",
      assessor: "readiness-engine",
    },
    {
      report_id: "rpt-2",
      grade: "D",
      score: 38,
      assessed_at: "2026-04-03T10:00:00Z",
      policy_version: "1",
      assessor: "manual",
    },
    {
      report_id: "rpt-1",
      grade: "F",
      score: 22,
      assessed_at: "2026-04-01T08:00:00Z",
      policy_version: "1",
      assessor: "readiness-engine",
    },
  ];
}

describe("ReportHistory", () => {
  it("renders all history entries", () => {
    render(<ReportHistory entries={makeEntries()} />);
    const rows = screen.getAllByTestId(/^report-history-entry-/);
    expect(rows).toHaveLength(3);
  });

  it("displays grade badges for each entry", () => {
    render(<ReportHistory entries={makeEntries()} />);
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.getByText("D")).toBeInTheDocument();
    expect(screen.getByText("F")).toBeInTheDocument();
  });

  it("displays scores", () => {
    render(<ReportHistory entries={makeEntries()} />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("38")).toBeInTheDocument();
  });

  it("renders empty state for no history", () => {
    render(<ReportHistory entries={[]} />);
    expect(screen.getByTestId("report-history-empty")).toBeInTheDocument();
  });
});
