/**
 * Tests for OverrideViewer component.
 *
 * AC-5: Evidence link renders as clickable <a target="_blank">.
 * AC-7: Active/revoked status display.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverrideViewer } from "./OverrideViewer";
import type { OverrideDetail } from "@/types/governance";

function makeOverride(overrides?: Partial<OverrideDetail>): OverrideDetail {
  return {
    id: "01HOVERRIDE000000000001",
    object_id: "01HCANDIDATE0000000001",
    object_type: "candidate",
    override_type: "grade_override",
    original_state: { grade: "C" },
    new_state: { grade: "B" },
    evidence_link: "https://jira.example.com/browse/FX-123",
    rationale: "Extended backtest justifies grade uplift over three-year window.",
    submitter_id: "01HUSER0000000000000001",
    status: "pending",
    reviewed_by: null,
    reviewed_at: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
    override_watermark: null,
    ...overrides,
  };
}

describe("OverrideViewer", () => {
  // -------------------------------------------------------------------------
  // Basic rendering
  // -------------------------------------------------------------------------

  it("renders override type and submitter", () => {
    render(<OverrideViewer override={makeOverride()} />);

    expect(screen.getByText("Grade Override")).toBeInTheDocument();
    expect(screen.getByTestId("override-submitter")).toHaveTextContent("01HUSER0000000000000001");
  });

  it("displays rationale text", () => {
    render(<OverrideViewer override={makeOverride()} />);

    expect(screen.getByTestId("override-rationale")).toHaveTextContent(
      "Extended backtest justifies grade uplift",
    );
  });

  it("displays original and new state JSON", () => {
    render(<OverrideViewer override={makeOverride()} />);

    expect(screen.getByTestId("override-original-state")).toHaveTextContent('"grade": "C"');
    expect(screen.getByTestId("override-new-state")).toHaveTextContent('"grade": "B"');
  });

  // -------------------------------------------------------------------------
  // Evidence link (AC-5)
  // -------------------------------------------------------------------------

  it("renders evidence link as clickable external link", () => {
    render(<OverrideViewer override={makeOverride()} />);

    const link = screen.getByTestId("override-evidence-link");
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "https://jira.example.com/browse/FX-123");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("does not render evidence link for javascript: URLs", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          evidence_link: "javascript:alert(1)",
        })}
      />,
    );

    expect(screen.queryByTestId("override-evidence-link")).not.toBeInTheDocument();
  });

  it("does not render evidence link for data: URLs", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          evidence_link: "data:text/html,<script>alert(1)</script>",
        })}
      />,
    );

    expect(screen.queryByTestId("override-evidence-link")).not.toBeInTheDocument();
  });

  it("renders valid http: evidence link", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          evidence_link: "http://internal.jira/RISK-99",
        })}
      />,
    );

    const link = screen.getByTestId("override-evidence-link");
    expect(link).toHaveAttribute("href", "http://internal.jira/RISK-99");
  });

  // -------------------------------------------------------------------------
  // Status display (AC-7)
  // -------------------------------------------------------------------------

  it("shows ACTIVE badge for approved overrides", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          status: "approved",
          reviewed_by: "01HUSER0000000000000002",
        })}
      />,
    );

    expect(screen.getByTestId("override-status-active")).toHaveTextContent("Active");
  });

  it("shows muted revoked label for rejected overrides", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          status: "rejected",
          reviewed_by: "01HUSER0000000000000002",
        })}
      />,
    );

    expect(screen.getByTestId("override-status-revoked")).toHaveTextContent("revoked");
  });

  it("shows Pending badge for pending overrides", () => {
    render(<OverrideViewer override={makeOverride()} />);

    expect(screen.getByTestId("override-status-pending")).toHaveTextContent("Pending");
  });

  // -------------------------------------------------------------------------
  // Reviewer and watermark
  // -------------------------------------------------------------------------

  it("renders reviewer when present", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          status: "approved",
          reviewed_by: "01HUSER0000000000000002",
          reviewed_at: "2026-04-06T14:00:00Z",
        })}
      />,
    );

    expect(screen.getByTestId("override-reviewer")).toHaveTextContent("01HUSER0000000000000002");
  });

  it("renders override watermark when present", () => {
    render(
      <OverrideViewer
        override={makeOverride({
          status: "approved",
          override_watermark: { override_id: "01HOVERRIDE", is_active: true },
        })}
      />,
    );

    expect(screen.getByTestId("override-watermark-detail")).toBeInTheDocument();
  });

  it("does not render watermark section when null", () => {
    render(<OverrideViewer override={makeOverride()} />);

    expect(screen.queryByTestId("override-watermark-detail")).not.toBeInTheDocument();
  });
});
