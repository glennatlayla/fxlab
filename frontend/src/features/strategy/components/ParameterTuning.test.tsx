/**
 * Tests for ParameterTuning component.
 *
 * Verifies that:
 *   - A form field is rendered for each parameter definition
 *   - Number inputs are rendered with min/max bounds for numeric parameters
 *   - Select dropdowns are rendered for choice-type parameters
 *   - Checkboxes are rendered for boolean parameters
 *   - Validation error is shown when min > max (contradictory bounds)
 *   - Submit button is disabled when bounds are contradictory
 *   - onSubmit callback is called with parameter values on valid submission
 *   - Default values are shown in form fields
 *
 * Dependencies:
 *   - vitest for assertions and mocking
 *   - @testing-library/react for render, screen, and user interactions
 *   - @testing-library/user-event for form interaction
 *   - React component: ParameterTuning
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import type { ParameterDefinition } from "@/types/strategy";
import { ParameterTuning } from "./ParameterTuning";

describe("ParameterTuning", () => {
  const mockParameters: ParameterDefinition[] = [
    {
      name: "lookback_period",
      label: "Lookback Period",
      type: "int",
      defaultValue: 20,
      min: 5,
      max: 500,
      step: 1,
      description: "Number of candles to include in lookback window",
      required: true,
    },
    {
      name: "rsi_threshold",
      label: "RSI Threshold",
      type: "float",
      defaultValue: 30.0,
      min: 0,
      max: 100,
      step: 0.5,
      description: "RSI oversold threshold for entry signals",
      required: true,
    },
    {
      name: "use_filters",
      label: "Use Entry Filters",
      type: "bool",
      defaultValue: true,
      description: "Enable market condition filters",
      required: false,
    },
    {
      name: "filter_mode",
      label: "Filter Mode",
      type: "choice",
      defaultValue: "aggressive",
      choices: ["conservative", "balanced", "aggressive"],
      description: "Level of market filtering",
      required: true,
    },
  ];

  const mockOnSubmit = vi.fn();

  describe("form field rendering", () => {
    it("renders a form field for each parameter definition", () => {
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);
      expect(screen.getByLabelText("Lookback Period")).toBeInTheDocument();
      expect(screen.getByLabelText("RSI Threshold")).toBeInTheDocument();
      expect(screen.getByLabelText("Use Entry Filters")).toBeInTheDocument();
      expect(screen.getByLabelText("Filter Mode")).toBeInTheDocument();
    });

    it("renders number input with min/max for numeric parameters", () => {
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);
      const lookbackInput = screen.getByLabelText("Lookback Period") as HTMLInputElement;
      expect(lookbackInput.type).toBe("number");
      expect(lookbackInput.min).toBe("5");
      expect(lookbackInput.max).toBe("500");
      expect(lookbackInput.defaultValue).toBe("20");
    });

    it("renders select for choice-type parameters", () => {
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);
      const select = screen.getByLabelText("Filter Mode") as HTMLSelectElement;
      expect(select.tagName).toBe("SELECT");
      const options = Array.from(select.options).map((opt) => opt.value);
      expect(options).toContain("conservative");
      expect(options).toContain("balanced");
      expect(options).toContain("aggressive");
    });

    it("renders checkbox for boolean parameters", () => {
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);
      const checkbox = screen.getByLabelText("Use Entry Filters") as HTMLInputElement;
      expect(checkbox.type).toBe("checkbox");
      expect(checkbox.defaultChecked).toBe(true);
    });

    it("shows default values in form fields", () => {
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);
      const lookbackInput = screen.getByLabelText("Lookback Period") as HTMLInputElement;
      expect(lookbackInput.value).toBe("20");

      const rsiInput = screen.getByLabelText("RSI Threshold") as HTMLInputElement;
      expect(rsiInput.value).toBe("30");

      const filterCheckbox = screen.getByLabelText("Use Entry Filters") as HTMLInputElement;
      expect(filterCheckbox.checked).toBe(true);

      const filterSelect = screen.getByLabelText("Filter Mode") as HTMLSelectElement;
      expect(filterSelect.value).toBe("aggressive");
    });
  });

  describe("validation and submission", () => {
    it("shows validation error when min > max (contradictory bounds)", async () => {
      const user = userEvent.setup();
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);

      const lookbackInput = screen.getByLabelText("Lookback Period") as HTMLInputElement;
      await user.clear(lookbackInput);
      await user.type(lookbackInput, "600"); // exceeds max of 500

      expect(screen.getByText(/invalid range|exceeds maximum/i)).toBeInTheDocument();
    });

    it("disables submit button when bounds are contradictory", async () => {
      const user = userEvent.setup();
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);

      const lookbackInput = screen.getByLabelText("Lookback Period") as HTMLInputElement;
      await user.clear(lookbackInput);
      await user.type(lookbackInput, "600"); // exceeds max of 500

      const submitButton = screen.getByRole("button", { name: /submit|save|apply/i });
      expect(submitButton).toBeDisabled();
    });

    it("calls onSubmit with parameter values on valid form submission", async () => {
      const user = userEvent.setup();
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);

      const lookbackInput = screen.getByLabelText("Lookback Period") as HTMLInputElement;
      await user.clear(lookbackInput);
      await user.type(lookbackInput, "50");

      const rsiInput = screen.getByLabelText("RSI Threshold") as HTMLInputElement;
      await user.clear(rsiInput);
      await user.type(rsiInput, "35.5");

      const submitButton = screen.getByRole("button", { name: /submit|save|apply/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            lookback_period: 50,
            rsi_threshold: 35.5,
            use_filters: true,
            filter_mode: "aggressive",
          }),
        );
      });
    });

    it("preserves default values if user does not modify them", async () => {
      const user = userEvent.setup();
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);

      const submitButton = screen.getByRole("button", { name: /submit|save|apply/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            lookback_period: 20,
            rsi_threshold: 30,
            use_filters: true,
            filter_mode: "aggressive",
          }),
        );
      });
    });
  });

  describe("edge cases", () => {
    it("renders with empty parameter list", () => {
      render(<ParameterTuning parameters={[]} onSubmit={mockOnSubmit} />);
      const submitButton = screen.getByRole("button", { name: /submit|save|apply/i });
      // Submit button should still be available for empty list
      expect(submitButton).toBeInTheDocument();
    });

    it("respects step value for numeric inputs", () => {
      render(<ParameterTuning parameters={mockParameters} onSubmit={mockOnSubmit} />);
      const rsiInput = screen.getByLabelText("RSI Threshold") as HTMLInputElement;
      expect(rsiInput.step).toBe("0.5");
    });
  });
});
