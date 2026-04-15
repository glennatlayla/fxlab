/**
 * Tests for OverrideWatermarkBanner component.
 *
 * AC-4: Override watermark renders in amber when active override applies.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverrideWatermarkBanner } from "./OverrideWatermarkBanner";
import type { OverrideWatermark } from "@/types/readiness";

function makeWatermark(overrides?: Partial<OverrideWatermark>): OverrideWatermark {
  return {
    override_id: "01HOVERRIDE00000000000001",
    is_active: true,
    override_type: "grade_override",
    rationale: "Approved by CRO for time-sensitive deployment",
    evidence_link: "https://jira.example.com/RISK-1234",
    created_at: "2026-04-01T10:00:00Z",
    ...overrides,
  };
}

describe("OverrideWatermarkBanner", () => {
  it("renders watermark banner", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark()} />);
    expect(screen.getByTestId("override-watermark-banner")).toBeInTheDocument();
  });

  it("applies amber styling for active overrides", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark()} />);
    const banner = screen.getByTestId("override-watermark-banner");
    expect(banner.className).toContain("amber");
  });

  it("displays the rationale text", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark()} />);
    expect(screen.getByText("Approved by CRO for time-sensitive deployment")).toBeInTheDocument();
  });

  it("displays the override type", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark()} />);
    expect(screen.getByText(/grade override/i)).toBeInTheDocument();
  });

  it("renders evidence link as clickable external link", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark()} />);
    const link = screen.getByRole("link", { name: /evidence/i });
    expect(link).toHaveAttribute("href", "https://jira.example.com/RISK-1234");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("hides evidence link when not provided", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark({ evidence_link: null })} />);
    expect(screen.queryByRole("link", { name: /evidence/i })).not.toBeInTheDocument();
  });

  it("has role=alert for accessibility", () => {
    render(<OverrideWatermarkBanner watermark={makeWatermark()} />);
    const banner = screen.getByTestId("override-watermark-banner");
    expect(banner).toHaveAttribute("role", "alert");
  });

  it("sanitizes javascript: URLs by not rendering the link", () => {
    render(
      <OverrideWatermarkBanner
        watermark={makeWatermark({ evidence_link: "javascript:alert(1)" })}
      />,
    );
    expect(screen.queryByRole("link", { name: /evidence/i })).not.toBeInTheDocument();
  });

  it("sanitizes data: URLs by not rendering the link", () => {
    render(
      <OverrideWatermarkBanner
        watermark={makeWatermark({ evidence_link: "data:text/html,<script>alert(1)</script>" })}
      />,
    );
    expect(screen.queryByRole("link", { name: /evidence/i })).not.toBeInTheDocument();
  });

  it("sanitizes ftp: URLs by not rendering the link", () => {
    render(
      <OverrideWatermarkBanner
        watermark={makeWatermark({ evidence_link: "ftp://evil.example.com/payload" })}
      />,
    );
    expect(screen.queryByRole("link", { name: /evidence/i })).not.toBeInTheDocument();
  });

  it("sanitizes blob: URLs by not rendering the link", () => {
    render(
      <OverrideWatermarkBanner
        watermark={makeWatermark({ evidence_link: "blob:http://example.com/abc" })}
      />,
    );
    expect(screen.queryByRole("link", { name: /evidence/i })).not.toBeInTheDocument();
  });

  it("renders valid http: URLs", () => {
    render(
      <OverrideWatermarkBanner
        watermark={makeWatermark({ evidence_link: "http://jira.internal/RISK-99" })}
      />,
    );
    const link = screen.getByRole("link", { name: /evidence/i });
    expect(link).toHaveAttribute("href", "http://jira.internal/RISK-99");
  });
});
