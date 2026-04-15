/**
 * Tests for RunStatusBadge component.
 *
 * Verifies correct rendering for each status value, ARIA attributes,
 * and the running status pulse animation indicator.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunStatusBadge } from "./RunStatusBadge";
import type { RunStatus } from "@/types/run";

describe("RunStatusBadge", () => {
  const statuses: RunStatus[] = ["pending", "running", "complete", "failed", "cancelled"];

  it.each(statuses)("renders '%s' status with correct label", (status) => {
    render(<RunStatusBadge status={status} />);
    const badge = screen.getByTestId("run-status-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent?.toLowerCase()).toContain(status === "complete" ? "complete" : status);
  });

  it("includes role='status' for accessibility", () => {
    render(<RunStatusBadge status="running" />);
    const badge = screen.getByRole("status");
    expect(badge).toBeInTheDocument();
  });

  it("shows aria-label with status name", () => {
    render(<RunStatusBadge status="failed" />);
    const badge = screen.getByTestId("run-status-badge");
    expect(badge.getAttribute("aria-label")).toBe("Run status: Failed");
  });

  it("shows pulse indicator for running status", () => {
    const { container } = render(<RunStatusBadge status="running" />);
    const pulseEl = container.querySelector(".animate-pulse");
    expect(pulseEl).toBeInTheDocument();
  });

  it("does not show pulse indicator for non-running statuses", () => {
    const { container } = render(<RunStatusBadge status="complete" />);
    const pulseEl = container.querySelector(".animate-pulse");
    expect(pulseEl).not.toBeInTheDocument();
  });

  it("applies custom className", () => {
    render(<RunStatusBadge status="pending" className="ml-2" />);
    const badge = screen.getByTestId("run-status-badge");
    expect(badge.className).toContain("ml-2");
  });
});
