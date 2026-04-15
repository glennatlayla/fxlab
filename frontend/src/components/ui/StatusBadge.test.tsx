/**
 * Tests for StatusBadge component.
 *
 * Verifies that known statuses render with correct styling and that
 * unknown statuses fall back to the neutral variant.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the status text", () => {
    render(<StatusBadge status="approved" />);
    expect(screen.getByText("approved")).toBeInTheDocument();
  });

  it("renders with green styling for 'approved'", () => {
    render(<StatusBadge status="approved" />);
    const badge = screen.getByText("approved");
    expect(badge.className).toContain("text-green-700");
  });

  it("renders with yellow styling for 'pending'", () => {
    render(<StatusBadge status="pending" />);
    const badge = screen.getByText("pending");
    expect(badge.className).toContain("text-yellow-700");
  });

  it("renders with red styling for 'rejected'", () => {
    render(<StatusBadge status="rejected" />);
    const badge = screen.getByText("rejected");
    expect(badge.className).toContain("text-red-700");
  });

  it("renders unknown status with neutral styling", () => {
    render(<StatusBadge status="custom_status" />);
    const badge = screen.getByText("custom status");
    expect(badge.className).toContain("text-surface-600");
  });

  it("replaces underscores with spaces in display text", () => {
    render(<StatusBadge status="in_progress" />);
    expect(screen.getByText("in progress")).toBeInTheDocument();
  });
});
