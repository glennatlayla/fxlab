/**
 * Tests for StaleDataIndicator component.
 *
 * Verifies:
 *   - Renders stale data warning with formatted timestamp.
 *   - Uses safeParseDateMs for safe date formatting.
 *   - Falls back to raw string when date is unparseable.
 *   - Applies custom className.
 *   - Includes required accessibility attributes (role, aria-live).
 *   - Has correct data-testid for integration testing.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StaleDataIndicator } from "./StaleDataIndicator";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StaleDataIndicator", () => {
  it("renders with a valid ISO-8601 timestamp", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    expect(indicator).toBeDefined();
    // Should contain formatted time (locale-dependent, so check pattern)
    expect(indicator.textContent).toContain("Data stale as of");
    // safeParseDateMs should parse this successfully, resulting in toLocaleTimeString output
    // We can't predict exact format (locale-dependent), but it should NOT be the raw ISO string
    expect(indicator.textContent).not.toContain("2026-04-04T10:30:00Z");
  });

  it("falls back to raw string when date is unparseable", () => {
    render(<StaleDataIndicator lastUpdatedAt="not-a-valid-date" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    expect(indicator.textContent).toContain("not-a-valid-date");
  });

  it("has role='alert' for accessibility", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    expect(indicator.getAttribute("role")).toBe("alert");
  });

  it("has aria-live='polite' for screen readers", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    expect(indicator.getAttribute("aria-live")).toBe("polite");
  });

  it("applies custom className", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" className="mt-4" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    expect(indicator.className).toContain("mt-4");
  });

  it("does not include extra space when className is empty", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    // className should not end with whitespace (trim applied)
    expect(indicator.className).not.toMatch(/\s$/);
  });

  it("renders warning icon (svg element)", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    const svg = indicator.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
  });

  it("applies warning colour classes", () => {
    render(<StaleDataIndicator lastUpdatedAt="2026-04-04T10:30:00Z" />);

    const indicator = screen.getByTestId("stale-data-indicator");
    expect(indicator.className).toContain("border-yellow-600");
    expect(indicator.className).toContain("text-yellow-300");
  });
});
