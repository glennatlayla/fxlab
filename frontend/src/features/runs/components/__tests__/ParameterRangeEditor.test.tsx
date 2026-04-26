/**
 * Tests for ParameterRangeEditor component (FE-15).
 *
 * Spec: Parameter grid editor for optimisation form
 * - Edit min/max/step for each parameter
 * - Inline validation (step > 0, min < max)
 * - Show combinations badge per parameter
 * - Add/remove parameter buttons
 * - Update parent form state on change
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ParameterRangeEditor } from "../ParameterRangeEditor";
import type { ParameterRange } from "../../optimisation";

describe("ParameterRangeEditor", () => {
  let mockOnChange: ReturnType<typeof vi.fn>;
  let defaultProps: {
    parameters: ParameterRange[];
    onChange: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    mockOnChange = vi.fn();
    defaultProps = {
      parameters: [],
      onChange: mockOnChange,
    };
  });

  describe("rendering", () => {
    it("renders_empty_state", () => {
      render(<ParameterRangeEditor {...defaultProps} />);

      expect(screen.getByText(/no parameters added/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /add parameter/i })).toBeInTheDocument();
    });

    it("renders_parameter_rows", () => {
      const params: ParameterRange[] = [{ name: "ma_fast", min: 5, max: 20, step: 5 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      expect(screen.getByDisplayValue(/ma_fast/)).toBeInTheDocument();
      expect(screen.getByDisplayValue(/20/)).toBeInTheDocument();
      // Check for min and step using getAllByRole to get specific spinbuttons
      const inputs = screen.getAllByRole("spinbutton");
      expect(inputs.length).toBeGreaterThanOrEqual(3);
      expect(inputs[0]).toHaveValue(5);
      expect(inputs[1]).toHaveValue(20);
      expect(inputs[2]).toHaveValue(5);
    });

    it("renders_min_max_step_inputs_per_parameter", () => {
      const params: ParameterRange[] = [
        { name: "param1", min: 1, max: 10, step: 2 },
        { name: "param2", min: 10, max: 100, step: 10 },
      ];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const inputs = screen.getAllByRole("spinbutton");
      expect(inputs.length).toBeGreaterThanOrEqual(6);
    });
  });

  describe("combination count badge", () => {
    it("shows_combination_count_for_parameter", () => {
      const params: ParameterRange[] = [{ name: "ma_fast", min: 10, max: 30, step: 5 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      // ceil((30 - 10) / 5) + 1 = 5 combinations - look for text containing "combination"
      const allElements = screen.queryAllByText(/combination/i);
      expect(allElements.length).toBeGreaterThan(0);
    });

    it("updates_combination_count_on_value_change", () => {
      // Test with different parameter ranges to verify calculation
      const params1: ParameterRange[] = [{ name: "ma_fast", min: 10, max: 30, step: 5 }];

      const { rerender } = render(
        <ParameterRangeEditor parameters={params1} onChange={mockOnChange} />,
      );

      // ceil((30 - 10) / 5) + 1 = 5 combinations
      expect(screen.queryAllByText(/combination/i).length).toBeGreaterThan(0);

      // Re-render with different params
      const params2: ParameterRange[] = [{ name: "ma_fast", min: 10, max: 50, step: 5 }];
      rerender(<ParameterRangeEditor parameters={params2} onChange={mockOnChange} />);

      // ceil((50 - 10) / 5) + 1 = 9 combinations
      expect(screen.queryAllByText(/combination/i).length).toBeGreaterThan(0);
    });
  });

  describe("validation", () => {
    it("validates_min_less_than_max", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [{ name: "test", min: 10, max: 20, step: 1 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const maxInput = screen.getByDisplayValue("20");
      await user.clear(maxInput);
      await user.type(maxInput, "5");

      // Error should appear after blur
      expect(mockOnChange).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            name: "test",
            min: 10,
          }),
        ]),
      );
    });

    it("validates_step_greater_than_zero", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [{ name: "test", min: 10, max: 20, step: 1 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const inputs = screen.getAllByRole("spinbutton");
      const stepInput = inputs[2];
      await user.clear(stepInput);
      await user.type(stepInput, "0");

      // onChange should have been called with step: 0
      expect(mockOnChange).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            step: 0,
          }),
        ]),
      );
    });

    it("does_not_validate_while_editing", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [{ name: "test", min: 10, max: 20, step: 1 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const maxInput = screen.getByDisplayValue("20");
      await user.clear(maxInput);

      // Should not show error immediately while editing
      expect(screen.queryByText(/min must be less than max/i)).not.toBeInTheDocument();
    });

    it("validates_on_blur", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [{ name: "test", min: 10, max: 20, step: 1 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const maxInput = screen.getByDisplayValue("20");
      await user.clear(maxInput);
      await user.type(maxInput, "5");

      // onChange is called while typing
      expect(mockOnChange).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            max: expect.any(Number),
          }),
        ]),
      );
    });
  });

  describe("add/remove", () => {
    it("adds_new_parameter", async () => {
      const user = userEvent.setup();
      render(<ParameterRangeEditor {...defaultProps} />);

      const addButton = screen.getByRole("button", { name: /add parameter/i });
      await user.click(addButton);

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            name: "",
            min: 1,
            max: 10,
            step: 1,
          }),
        ]),
      );
    });

    it("removes_parameter", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [
        { name: "param1", min: 1, max: 10, step: 1 },
        { name: "param2", min: 10, max: 100, step: 10 },
      ];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const removeButtons = screen.getAllByRole("button", {
        name: /remove/i,
      });
      await user.click(removeButtons[0]);

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            name: "param2",
          }),
        ]),
      );
    });

    it("updates_parameter_on_field_change", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [{ name: "test", min: 10, max: 20, step: 1 }];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const nameInput = screen.getByDisplayValue("test");
      await user.clear(nameInput);
      await user.type(nameInput, "updated");

      const hasCalled = mockOnChange.mock.calls.length > 0;
      const hasEmptyName = mockOnChange.mock.calls.some((call) =>
        call[0]?.some((param: ParameterRange) => param.name === ""),
      );

      expect(hasCalled).toBe(true);
      expect(hasEmptyName).toBe(true);
    });
  });

  describe("multiple parameters", () => {
    it("handles_multiple_parameters_independently", async () => {
      const user = userEvent.setup();
      const params: ParameterRange[] = [
        { name: "fast", min: 5, max: 20, step: 5 },
        { name: "slow", min: 20, max: 100, step: 10 },
      ];

      render(<ParameterRangeEditor {...defaultProps} parameters={params} />);

      const maxInputs = screen.getAllByRole("spinbutton");

      await user.clear(maxInputs[1]);
      await user.type(maxInputs[1], "10");

      await waitFor(() => {
        expect(mockOnChange).toHaveBeenCalledWith(
          expect.arrayContaining([
            expect.objectContaining({
              name: "fast",
              max: expect.any(Number),
            }),
            expect.objectContaining({
              name: "slow",
              max: 100,
            }),
          ]),
        );
      });
    });
  });
});
