/**
 * RiskSettingsCard unit tests.
 *
 * Purpose:
 *   Verify RiskSettingsCard component displays current risk limits correctly
 *   and handles inline editing of individual fields.
 *
 * Test coverage:
 *   - Renders all risk limit fields with current values.
 *   - Shows edit pencil icon for each field.
 *   - Clicking pencil enables inline edit mode for that field.
 *   - Color codes limits: green for conservative, amber for moderate, red for aggressive.
 *   - Saves edited value and exits edit mode on blur or Enter.
 *   - Reverts to current value on Escape.
 *   - Disables edit when isLoading=true.
 *
 * Dependencies:
 *   - vitest, @testing-library/react, @testing-library/user-event
 *   - RiskSettingsCard component
 *
 * Example:
 *   npx vitest run src/features/risk/components/__tests__/RiskSettingsCard.test.tsx -xvs
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RiskSettingsCard } from "../RiskSettingsCard";
import type { RiskSettings } from "../../types";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * Create a mock RiskSettings object with realistic values.
 */
function mockSettings(overrides?: Partial<RiskSettings>): RiskSettings {
  return {
    deployment_id: "01HDEPLOY123",
    max_position_size: "10000",
    max_daily_loss: "5000",
    max_order_value: "50000",
    max_concentration_pct: "25",
    max_open_orders: 100,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RiskSettingsCard", () => {
  it("renders all risk limit fields with current values", () => {
    const settings = mockSettings();

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={false} />,
    );

    // Check all fields are rendered using testid selectors for certainty
    expect(container.querySelector('[data-testid="field-max_position_size"]')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="field-max_daily_loss"]')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="field-max_order_value"]')).toBeInTheDocument();
    expect(
      container.querySelector('[data-testid="field-max_concentration_pct"]'),
    ).toBeInTheDocument();
    expect(container.querySelector('[data-testid="field-max_open_orders"]')).toBeInTheDocument();

    // Check labels render
    expect(screen.getByText("Max Position Size")).toBeInTheDocument();
    expect(screen.getByText("Max Daily Loss")).toBeInTheDocument();
    expect(screen.getByText("Max Order Value")).toBeInTheDocument();
    expect(screen.getByText("Max Concentration %")).toBeInTheDocument();
    expect(screen.getByText("Max Open Orders")).toBeInTheDocument();
  });

  it("shows edit pencil icon for each field", () => {
    const settings = mockSettings();

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={false} />,
    );

    // Check for edit buttons (pencil icons)
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    expect(editButtons.length).toBeGreaterThanOrEqual(5);
  });

  it("enters inline edit mode when pencil icon is clicked", async () => {
    const user = userEvent.setup();
    const settings = mockSettings();

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={false} />,
    );

    // Find edit button for max_position_size
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    await user.click(editButtons[0]);

    // Should show input field with the original value (unformatted)
    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.tagName).toBe("INPUT");
  });

  it("calls onFieldChange callback when edited value is confirmed", async () => {
    const user = userEvent.setup();
    const onFieldChange = vi.fn();
    const settings = mockSettings();

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={onFieldChange} isLoading={false} />,
    );

    // Click edit button and change value
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    await user.click(editButtons[0]);

    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "15000");
    await user.keyboard("{Enter}");

    expect(onFieldChange).toHaveBeenCalledWith("max_position_size", "15000");
  });

  it("reverts to current value when Escape is pressed during edit", async () => {
    const user = userEvent.setup();
    const onFieldChange = vi.fn();
    const settings = mockSettings();

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={onFieldChange} isLoading={false} />,
    );

    // Click edit button and start changing value
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    await user.click(editButtons[0]);

    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "15000");
    await user.keyboard("{Escape}");

    // Should exit edit mode and revert
    expect(onFieldChange).not.toHaveBeenCalled();
    expect(screen.queryByDisplayValue("15000")).not.toBeInTheDocument();
  });

  it("color codes conservative limits in green", () => {
    const settings = mockSettings({
      max_position_size: "1000000", // Conservative (very high limit)
    });

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={false} />,
    );

    // Check for green coloring (conservative)
    const row = container.querySelector("[data-testid='field-max_position_size']");
    expect(row).toHaveClass("bg-green-50");
  });

  it("color codes moderate limits in amber", () => {
    const settings = mockSettings({
      max_position_size: "50000", // Moderate
    });

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={false} />,
    );

    // Check for amber coloring (moderate)
    const row = container.querySelector("[data-testid='field-max_position_size']");
    expect(row).toHaveClass("bg-amber-50");
  });

  it("color codes aggressive limits in red", () => {
    const settings = mockSettings({
      max_position_size: "5000", // Aggressive (low limit)
    });

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={false} />,
    );

    // Check for red coloring (aggressive)
    const row = container.querySelector("[data-testid='field-max_position_size']");
    expect(row).toHaveClass("bg-red-50");
  });

  it("disables edit buttons when isLoading=true", () => {
    const settings = mockSettings();

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={vi.fn()} isLoading={true} />,
    );

    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    editButtons.forEach((btn) => {
      expect(btn).toBeDisabled();
    });
  });

  it("handles numeric fields correctly (max_open_orders as integer)", async () => {
    const user = userEvent.setup();
    const onFieldChange = vi.fn();
    const settings = mockSettings({ max_open_orders: 50 });

    const { container } = render(
      <RiskSettingsCard settings={settings} onFieldChange={onFieldChange} isLoading={false} />,
    );

    // Find edit button for max_open_orders (last field)
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    await user.click(editButtons[4]);

    const input = screen.getByDisplayValue("50") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "75");
    await user.keyboard("{Enter}");

    expect(onFieldChange).toHaveBeenCalledWith("max_open_orders", 75);
  });
});
