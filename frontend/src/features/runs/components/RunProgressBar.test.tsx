/**
 * Tests for RunProgressBar component.
 *
 * Verifies correct percentage calculation, label display,
 * ARIA progressbar attributes, and colour changes per status.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunProgressBar } from "./RunProgressBar";

describe("RunProgressBar", () => {
  it("renders trial count label", () => {
    render(<RunProgressBar completedTrials={42} totalTrials={100} status="running" />);
    expect(screen.getByText("42 / 100 (42%)")).toBeInTheDocument();
  });

  it("calculates percentage correctly", () => {
    render(<RunProgressBar completedTrials={25} totalTrials={100} status="running" />);
    const progressbar = screen.getByRole("progressbar");
    expect(progressbar.getAttribute("aria-valuenow")).toBe("25");
  });

  it("handles zero total trials gracefully", () => {
    render(<RunProgressBar completedTrials={0} totalTrials={0} status="pending" />);
    expect(screen.getByText("0 / 0 (0%)")).toBeInTheDocument();
    const progressbar = screen.getByRole("progressbar");
    expect(progressbar.getAttribute("aria-valuenow")).toBe("0");
  });

  it("shows 100% for completed runs", () => {
    render(<RunProgressBar completedTrials={50} totalTrials={50} status="complete" />);
    expect(screen.getByText("50 / 50 (100%)")).toBeInTheDocument();
  });

  it("uses green colour for complete status", () => {
    const { container } = render(
      <RunProgressBar completedTrials={50} totalTrials={50} status="complete" />,
    );
    const fillBar = container.querySelector("[style]");
    expect(fillBar?.className).toContain("bg-green-500");
  });

  it("uses red colour for failed status", () => {
    const { container } = render(
      <RunProgressBar completedTrials={30} totalTrials={100} status="failed" />,
    );
    const fillBar = container.querySelector("[style]");
    expect(fillBar?.className).toContain("bg-red-500");
  });

  it("applies animate-pulse for running status", () => {
    const { container } = render(
      <RunProgressBar completedTrials={30} totalTrials={100} status="running" />,
    );
    const fillBar = container.querySelector("[style]");
    expect(fillBar?.className).toContain("animate-pulse");
  });
});
