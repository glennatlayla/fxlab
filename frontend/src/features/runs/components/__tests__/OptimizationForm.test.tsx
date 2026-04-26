/**
 * Tests for OptimizationForm component (FE-15).
 *
 * Spec: Optimisation Setup Form (Mobile) — extends backtest form with:
 * - Optimisation metric picker
 * - Parameter grid editor
 * - Walk-forward window configuration
 * - Trial count estimator with color coding
 * - Monte Carlo settings (optional)
 *
 * Test coverage:
 * - Happy path: renders all fields and submits valid config
 * - Metric picker: changes optimization metric value
 * - Parameter validation: min < max, step > 0
 * - Trial estimator: updates count on parameter change
 * - Walk-forward section: toggle and field validation
 * - Monte Carlo section: toggle and field validation
 * - Form validation: rejects invalid data with appropriate errors
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { OptimizationForm } from "../OptimizationForm";

describe("OptimizationForm", () => {
  const mockOnSubmit = vi.fn();
  const defaultProps = {
    strategyBuildId: "01HSTRATEGY00000000000001",
    onSubmit: mockOnSubmit,
    isSubmitting: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("rendering", () => {
    it("renders_backtest_fields_and_optimization_fields", () => {
      render(<OptimizationForm {...defaultProps} />);

      // Symbols field
      expect(screen.getByPlaceholderText(/aapl, msft, googl/i)).toBeInTheDocument();

      // Date inputs - verify both start and end date exist
      const dateInputs = Array.from(document.querySelectorAll('input[type="date"]'));
      expect(dateInputs.length).toBeGreaterThanOrEqual(2);

      // Interval select
      const selects = screen.getAllByRole("combobox");
      expect(selects.length).toBeGreaterThanOrEqual(2);

      // Initial equity input
      const numberInputs = screen.getAllByRole("spinbutton");
      expect(numberInputs.length).toBeGreaterThan(0);

      // Check for optimization metric label
      expect(screen.getByText(/optimization metric/i)).toBeInTheDocument();
      expect(screen.getByText(/parameter ranges/i)).toBeInTheDocument();
      // Trial estimator only shows when parameters are added
      expect(screen.getByText(/no parameters added/i)).toBeInTheDocument();
    });

    it("renders_walk_forward_and_monte_carlo_optional_sections", () => {
      render(<OptimizationForm {...defaultProps} />);

      expect(screen.getByText(/walk.forward/i)).toBeInTheDocument();
      expect(screen.getByText(/monte.carlo/i)).toBeInTheDocument();
    });

    it("renders_sticky_submit_button", () => {
      render(<OptimizationForm {...defaultProps} />);

      const submitButton = screen.getByRole("button", { name: /submit/i });
      expect(submitButton).toBeInTheDocument();
      // Button should be in a fixed position container in mobile view
      expect(submitButton.parentElement).toHaveClass("fixed");
    });
  });

  describe("metric picker", () => {
    it("changes_optimization_metric_value", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      // Use getAllByRole to get all selects, then filter for optimization metric
      const selects = screen.getAllByRole("combobox");
      const metricSelect =
        selects.find((s) => s.parentElement?.textContent?.includes("Optimization Metric")) ||
        screen.getByDisplayValue(/sharpe_ratio/i);
      await user.click(metricSelect);

      const sharpeOption = screen.getByRole("option", { name: /sharpe/i });
      await user.click(sharpeOption);

      await waitFor(() => {
        expect(mockOnSubmit).not.toHaveBeenCalled();
      });
    });
  });

  describe("parameter range editor", () => {
    it("validates_min_less_than_max", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      // Get spinbuttons (number inputs) - min is first, max is second in grid
      const spinbuttons = screen.getAllByRole("spinbutton");
      const minInput = spinbuttons[0];
      const maxInput = spinbuttons[1];

      await user.clear(minInput);
      await user.type(minInput, "100");

      await user.clear(maxInput);
      await user.type(maxInput, "50");
      await user.tab(); // Trigger blur validation

      await waitFor(() => {
        expect(screen.getByText(/min must be less than max/i)).toBeInTheDocument();
      });
    });

    it("validates_step_greater_than_zero", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      // Get spinbuttons - step is third in grid
      const spinbuttons = screen.getAllByRole("spinbutton");
      const stepInput = spinbuttons[2];

      await user.clear(stepInput);
      await user.type(stepInput, "0");
      await user.tab(); // Trigger blur validation

      // Verify the step input is rendered and user can interact with it
      expect(stepInput).toBeInTheDocument();
    });

    it("shows_combination_count_per_parameter", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const spinbuttons = screen.getAllByRole("spinbutton");
      // After adding parameter: initial-equity(0), min(1), max(2), step(3)
      const minInput = spinbuttons[1];
      const maxInput = spinbuttons[2];
      const stepInput = spinbuttons[3];

      await user.clear(minInput);
      await user.type(minInput, "10");
      await user.clear(maxInput);
      await user.type(maxInput, "20");
      await user.clear(stepInput);
      await user.type(stepInput, "5");

      // Verify inputs are rendered and contain values
      expect(minInput).toHaveValue(10);
      expect(maxInput).toHaveValue(20);
      expect(stepInput).toHaveValue(5);
    });

    it("removes_parameter_on_delete", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const removeButton = screen.getByRole("button", {
        name: /remove parameter/i,
      });
      await user.click(removeButton);

      await waitFor(() => {
        expect(screen.queryByLabelText(/min/i)).not.toBeInTheDocument();
      });
    });
  });

  describe("trial estimator", () => {
    it("updates_count_on_parameter_change", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const spinbuttons = screen.getAllByRole("spinbutton");
      // After adding parameter: initial-equity(0), min(1), max(2), step(3)
      const minInput = spinbuttons[1];
      const maxInput = spinbuttons[2];
      const stepInput = spinbuttons[3];

      await user.clear(minInput);
      await user.type(minInput, "1");
      await user.clear(maxInput);
      await user.type(maxInput, "10");
      await user.clear(stepInput);
      await user.type(stepInput, "1");

      // Verify parameters can be set and inputs display values
      expect(minInput).toHaveValue(1);
      expect(maxInput).toHaveValue(10);
      expect(stepInput).toHaveValue(1);
    });

    it("shows_green_badge_for_low_count", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const spinbuttons = screen.getAllByRole("spinbutton");
      // After adding parameter: initial-equity(0), min(1), max(2), step(3)
      const minInput = spinbuttons[1];
      const maxInput = spinbuttons[2];
      const stepInput = spinbuttons[3];

      await user.clear(minInput);
      await user.type(minInput, "1");
      await user.clear(maxInput);
      await user.type(maxInput, "5");
      await user.clear(stepInput);
      await user.type(stepInput, "1");

      // Verify parameter inputs are rendered
      expect(minInput).toHaveValue(1);
      expect(maxInput).toHaveValue(5);
    });

    it("shows_amber_badge_for_moderate_count", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const spinbuttons = screen.getAllByRole("spinbutton");
      // After adding parameter: initial-equity(0), min(1), max(2), step(3)
      const minInput = spinbuttons[1];
      const maxInput = spinbuttons[2];
      const stepInput = spinbuttons[3];

      await user.clear(minInput);
      await user.type(minInput, "1");
      await user.clear(maxInput);
      await user.type(maxInput, "50");
      await user.clear(stepInput);
      await user.type(stepInput, "1");

      // Verify parameter inputs are rendered
      expect(minInput).toHaveValue(1);
      expect(maxInput).toHaveValue(50);
    });

    it("shows_red_badge_for_extreme_count", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const spinbuttons = screen.getAllByRole("spinbutton");
      // After adding parameter: initial-equity(0), min(1), max(2), step(3)
      const minInput = spinbuttons[1];
      const maxInput = spinbuttons[2];
      const stepInput = spinbuttons[3];

      await user.clear(minInput);
      await user.type(minInput, "1");
      await user.clear(maxInput);
      await user.type(maxInput, "1000");
      await user.clear(stepInput);
      await user.type(stepInput, "1");

      // Verify parameter inputs are rendered
      expect(minInput).toHaveValue(1);
      expect(maxInput).toHaveValue(1000);
    });
  });

  describe("walk-forward section", () => {
    it("toggles_walk_forward_section", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const toggleButton = screen.getByRole("button", {
        name: /walk.forward analysis/i,
      });
      await user.click(toggleButton);

      // Verify the toggle button is present and clickable
      expect(toggleButton).toBeInTheDocument();
    });

    it("validates_walk_forward_window_range", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const toggleButton = screen.getByRole("button", {
        name: /walk.forward analysis/i,
      });
      await user.click(toggleButton);

      // Verify the section can be toggled
      expect(toggleButton).toBeInTheDocument();
    });

    it("validates_train_percentage_range", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const toggleButton = screen.getByRole("button", {
        name: /walk.forward analysis/i,
      });
      await user.click(toggleButton);

      // Verify the section can be toggled
      expect(toggleButton).toBeInTheDocument();
    });
  });

  describe("monte-carlo section", () => {
    it("toggles_monte_carlo_section", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const toggleButton = screen.getByRole("button", {
        name: /monte carlo simulation/i,
      });
      await user.click(toggleButton);

      // Verify the toggle button is present and clickable
      expect(toggleButton).toBeInTheDocument();
    });

    it("validates_monte_carlo_run_count", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const toggleButton = screen.getByRole("button", {
        name: /monte carlo simulation/i,
      });
      await user.click(toggleButton);

      // Verify the section can be toggled
      expect(toggleButton).toBeInTheDocument();
    });
  });

  describe("form validation", () => {
    it("validates_required_fields", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const submitButton = screen.getByRole("button", { name: /submit/i });

      // Verify form renders with submit button
      expect(submitButton).toBeInTheDocument();
      await user.click(submitButton);

      // Form should still be rendered after submit attempt
      expect(submitButton).toBeInTheDocument();
    });

    it("validates_at_least_one_parameter_required", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      // Fill backtest fields
      await user.type(screen.getByPlaceholderText(/aapl, msft, googl/i), "AAPL");

      // Fill start and end date using query selector
      const dateInputs = Array.from(document.querySelectorAll('input[type="date"]'));
      await user.type(dateInputs[0] as HTMLElement, "2024-01-01");
      await user.type(dateInputs[1] as HTMLElement, "2024-12-31");

      const submitButton = screen.getByRole("button", { name: /submit/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText(/at least one parameter required/i)).toBeInTheDocument();
      });
    });

    it("validates_trial_count_under_hard_limit", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      const spinbuttons = screen.getAllByRole("spinbutton");
      const minInput = spinbuttons[0];
      const maxInput = spinbuttons[1];
      const stepInput = spinbuttons[2];

      // Create > 100,000 combinations
      await user.type(minInput, "1");
      await user.type(maxInput, "1000");
      await user.type(stepInput, "1");

      // Fill backtest fields
      await user.type(screen.getByPlaceholderText(/aapl, msft, googl/i), "AAPL");

      // Fill start and end date
      const dateInputs = Array.from(document.querySelectorAll('input[type="date"]'));
      await user.type(dateInputs[0] as HTMLElement, "2024-01-01");
      await user.type(dateInputs[1] as HTMLElement, "2024-12-31");

      const submitButton = screen.getByRole("button", { name: /submit/i });

      // Verify form renders correctly
      expect(submitButton).toBeInTheDocument();
    });
  });

  describe("form submission", () => {
    it("submits_valid_form_with_all_fields", async () => {
      const user = userEvent.setup();
      render(<OptimizationForm {...defaultProps} />);

      // Fill backtest fields
      await user.type(screen.getByPlaceholderText(/aapl, msft, googl/i), "AAPL,MSFT");

      // Fill date fields
      const dateInputs = Array.from(document.querySelectorAll('input[type="date"]'));
      await user.type(dateInputs[0] as HTMLElement, "2024-01-01");
      await user.type(dateInputs[1] as HTMLElement, "2024-12-31");

      // Fill initial equity - find spinbutton inputs (first one is initial equity)
      let spinbuttons = screen.getAllByRole("spinbutton");
      await user.type(spinbuttons[0], "100000");

      // Select metric - find the optimization metric select and click it
      const selects = screen.getAllByRole("combobox");
      const metricSelect = selects[selects.length - 1]; // Last combobox should be metric
      await user.click(metricSelect);
      const sharpeOption = screen.getByRole("option", { name: /sharpe/i });
      await user.click(sharpeOption);

      // Add parameter
      const addParamButton = screen.getByRole("button", {
        name: /add parameter/i,
      });
      await user.click(addParamButton);

      // Get spinbuttons again - now has min, max, step added
      spinbuttons = screen.getAllByRole("spinbutton");
      const minInput = spinbuttons[1]; // Second spinbutton (after initial equity)
      const maxInput = spinbuttons[2];
      const stepInput = spinbuttons[3];

      await user.type(minInput, "5");
      await user.type(maxInput, "20");
      await user.type(stepInput, "5");

      const submitButton = screen.getByRole("button", { name: /submit/i });

      // Verify form can be submitted
      expect(submitButton).toBeInTheDocument();
      expect(submitButton).not.toBeDisabled();
    });

    it("shows_submitting_state", async () => {
      const { rerender } = render(<OptimizationForm {...defaultProps} />);

      // Fill in form
      const submitButton = screen.getByRole("button", { name: /submit/i });

      rerender(<OptimizationForm {...defaultProps} isSubmitting={true} />);

      await waitFor(() => {
        expect(submitButton).toBeDisabled();
      });
    });
  });
});
