/**
 * Tests for OverrideWatermarkBadge component.
 *
 * Verifies §8.2 requirements: ≥16px, amber colour, visible on run cards.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverrideWatermarkBadge } from "./OverrideWatermarkBadge";
import type { OverrideWatermark } from "@/types/run";

function makeActiveWatermark(): OverrideWatermark {
  return {
    override_id: "01HZ0000000000000000000099",
    approved_by: "admin@fxlab.io",
    approved_at: "2026-04-03T12:00:00Z",
    reason: "Emergency deployment required",
    revoked: false,
  };
}

describe("OverrideWatermarkBadge", () => {
  it("renders active override badge", () => {
    render(<OverrideWatermarkBadge watermark={makeActiveWatermark()} />);
    const badge = screen.getByTestId("override-watermark-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toContain("Override Active");
  });

  it("shows approved by and reason", () => {
    render(<OverrideWatermarkBadge watermark={makeActiveWatermark()} />);
    expect(screen.getByText(/admin@fxlab.io/)).toBeInTheDocument();
    expect(screen.getByText(/Emergency deployment required/)).toBeInTheDocument();
  });

  it("uses amber colours for active override", () => {
    render(<OverrideWatermarkBadge watermark={makeActiveWatermark()} />);
    const badge = screen.getByTestId("override-watermark-badge");
    expect(badge.className).toContain("border-amber-600");
  });

  it("renders revoked override with different styling", () => {
    const revokedWm = {
      ...makeActiveWatermark(),
      revoked: true,
      revoked_at: "2026-04-04T15:00:00Z",
    };
    render(<OverrideWatermarkBadge watermark={revokedWm} />);
    const badge = screen.getByTestId("override-watermark-badge");
    expect(badge.textContent).toContain("Override Revoked");
    expect(badge.className).toContain("border-gray-600");
  });

  it("has minimum height of 16px per spec §8.2", () => {
    render(<OverrideWatermarkBadge watermark={makeActiveWatermark()} />);
    const badge = screen.getByTestId("override-watermark-badge");
    expect(badge.style.minHeight).toBe("16px");
  });

  it("has accessible role and label", () => {
    render(<OverrideWatermarkBadge watermark={makeActiveWatermark()} />);
    const badge = screen.getByRole("alert");
    expect(badge.getAttribute("aria-label")).toBe("Active override");
  });
});
