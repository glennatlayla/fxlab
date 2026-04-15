/**
 * Tests for ReadinessViewer component.
 *
 * AC-1 (partial): Readiness report loads and grade renders.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReadinessViewer } from "./ReadinessViewer";

describe("ReadinessViewer", () => {
  const defaultProps = {
    grade: "B" as const,
    score: 72,
    policyVersion: "1",
    assessedAt: "2026-04-06T12:00:00Z",
    assessor: "readiness-engine",
  };

  it("renders the grade badge", () => {
    render(<ReadinessViewer {...defaultProps} />);
    expect(screen.getByTestId("grade-badge")).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
  });

  it("displays the overall score", () => {
    render(<ReadinessViewer {...defaultProps} />);
    expect(screen.getByText("72")).toBeInTheDocument();
  });

  it("displays the policy version prominently", () => {
    render(<ReadinessViewer {...defaultProps} />);
    expect(screen.getByText(/Policy v1/)).toBeInTheDocument();
  });

  it("displays the assessment timestamp", () => {
    render(<ReadinessViewer {...defaultProps} />);
    expect(screen.getByTestId("readiness-assessed-at")).toBeInTheDocument();
  });

  it("displays the assessor", () => {
    render(<ReadinessViewer {...defaultProps} />);
    // Assessor is rendered inside "By: readiness-engine" text node.
    expect(screen.getByText(/readiness-engine/)).toBeInTheDocument();
  });

  it("shows grade interpretation text", () => {
    render(<ReadinessViewer {...defaultProps} />);
    expect(screen.getByText(/monitoring/i)).toBeInTheDocument();
  });
});
