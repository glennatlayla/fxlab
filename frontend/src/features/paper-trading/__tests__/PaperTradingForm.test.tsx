/**
 * Unit tests for PaperTradingForm component.
 *
 * Purpose:
 *   Verify form rendering, field validation, state management,
 *   and submission flow.
 *
 * Coverage:
 *   - Renders all form fields (deployment, strategy, equity, risk limits, symbols).
 *   - Opens BottomSheet pickers for selection.
 *   - Validates required fields.
 *   - Validates numeric ranges (equity, leverage).
 *   - Shows/hides review based on completion.
 *   - Submits valid form and calls onSubmit callback.
 *
 * Example:
 *   test_paperTradingForm_renders_all_form_fields
 *   test_paperTradingForm_deployment_picker_opens
 *   test_paperTradingForm_validates_equity_minimum
 *   test_paperTradingForm_submit_calls_callback
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PaperTradingForm } from "../components/PaperTradingForm";
import type {
  DeploymentMetadata,
  StrategyBuildMetadata,
  PaperTradingConfig,
} from "../types";

/**
 * Helper: Create mock deployment metadata.
 */
function createMockDeployment(overrides?: Partial<DeploymentMetadata>): DeploymentMetadata {
  return {
    id: "01HDEPLOY123456789012345",
    name: "Test Deployment",
    status: "active",
    ...overrides,
  };
}

/**
 * Helper: Create mock strategy build metadata.
 */
function createMockStrategy(overrides?: Partial<StrategyBuildMetadata>): StrategyBuildMetadata {
  return {
    id: "01HSTRAT123456789012345",
    name: "Test Strategy",
    ...overrides,
  };
}

describe("PaperTradingForm", () => {
  /**
   * Test: Form renders all field groups.
   */
  it("should render all form field sections", () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    // Verify all major sections are rendered.
    expect(screen.getByText(/Deployment/)).toBeInTheDocument();
    expect(screen.getByText(/Strategy/)).toBeInTheDocument();
    expect(screen.getByText(/Initial Equity/)).toBeInTheDocument();
    expect(screen.getByText(/Risk Limits/)).toBeInTheDocument();
    expect(screen.getByText(/Trading Symbols/)).toBeInTheDocument();
  });

  /**
   * Test: Deployment picker button opens BottomSheet.
   */
  it("should open deployment picker when deployment button clicked", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    const deploymentButton = screen.getByRole("button", { name: /select deployment/i });
    await userEvent.click(deploymentButton);

    // Verify BottomSheet opens and shows deployment list.
    await waitFor(() => {
      expect(screen.getByText(mockDeployments[0].name)).toBeInTheDocument();
    });
  });

  /**
   * Test: Selecting a deployment updates form state.
   */
  it("should update form when deployment is selected", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment({ name: "Deployment A" })];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    const deploymentButton = screen.getByRole("button", { name: /select deployment/i });
    await userEvent.click(deploymentButton);

    const deploymentOption = screen.getByText("Deployment A");
    await userEvent.click(deploymentOption);

    // Verify deployment name appears on button.
    await waitFor(() => {
      expect(screen.getByText("Deployment A")).toBeInTheDocument();
    });
  });

  /**
   * Test: Strategy picker button opens BottomSheet.
   */
  it("should open strategy picker when strategy button clicked", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy({ name: "Strategy A" })];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    const strategyButton = screen.getByRole("button", { name: /select strategy/i });
    await userEvent.click(strategyButton);

    // Verify BottomSheet opens and shows strategy list.
    await waitFor(() => {
      expect(screen.getByText("Strategy A")).toBeInTheDocument();
    });
  });

  /**
   * Test: Equity input field accepts valid values.
   */
  it("should accept valid equity values", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    const equityInput = screen.getByDisplayValue("10000");
    await userEvent.clear(equityInput);
    await userEvent.type(equityInput, "50000");

    expect(equityInput).toHaveValue(50000);
  });

  /**
   * Test: Leverage input respects max value constraint.
   */
  it("should not accept leverage above 10x", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    const leverageInput = screen.getByRole("slider", { name: /leverage/i });
    fireEvent.change(leverageInput, { target: { value: 11 } });

    // Input may clamp, but should not exceed max.
    expect(parseInt(leverageInput.getAttribute("value") || "0")).toBeLessThanOrEqual(10);
  });

  /**
   * Test: Submit button is disabled when required fields missing.
   */
  it("should disable submit button when deployment not selected", () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    const submitButton = screen.getByRole("button", { name: /continue/i });
    expect(submitButton).toBeDisabled();
  });

  /**
   * Test: Submit button enabled when all required fields are set.
   */
  it("should enable submit button when all required fields are set", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    // Select deployment
    const deploymentButton = screen.getByRole("button", { name: /select deployment/i });
    await userEvent.click(deploymentButton);
    const deploymentOption = screen.getByText(mockDeployments[0].name);
    await userEvent.click(deploymentOption);

    // Select strategy
    const strategyButton = screen.getByRole("button", { name: /select strategy/i });
    await userEvent.click(strategyButton);
    const strategyOption = screen.getByText(mockStrategies[0].name);
    await userEvent.click(strategyOption);

    // Verify submit button is enabled
    await waitFor(() => {
      const submitButton = screen.getByRole("button", { name: /continue/i });
      expect(submitButton).not.toBeDisabled();
    });
  });

  /**
   * Test: Form displays loading state.
   */
  it("should show loading state when isLoading is true", () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={true}
        onSubmit={mockOnSubmit}
      />,
    );

    const submitButton = screen.getByRole("button", { name: /loading/i });
    expect(submitButton).toBeDisabled();
  });

  /**
   * Test: Form displays error message when provided.
   */
  it("should display error message when error prop is set", () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];
    const errorMessage = "Failed to start paper trading";

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        error={errorMessage}
        onSubmit={mockOnSubmit}
      />,
    );

    expect(screen.getByText(errorMessage)).toBeInTheDocument();
  });

  /**
   * Test: Submit is disabled when equity below minimum.
   */
  it("should disable submit when equity below minimum", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    // Select deployment and strategy first
    const deploymentButton = screen.getByRole("button", { name: /select deployment/i });
    await userEvent.click(deploymentButton);
    await userEvent.click(screen.getByText(mockDeployments[0].name));

    const strategyButton = screen.getByRole("button", { name: /select strategy/i });
    await userEvent.click(strategyButton);
    await userEvent.click(screen.getByText(mockStrategies[0].name));

    // Set equity below minimum
    const equityInput = screen.getByDisplayValue("10000");
    await userEvent.clear(equityInput);
    await userEvent.type(equityInput, "500");

    // Submit should still be disabled
    const submitButton = screen.getByRole("button", { name: /continue/i });
    expect(submitButton).toBeDisabled();
  });

  /**
   * Test: Calling submit with valid data invokes onSubmit callback.
   */
  it("should call onSubmit callback with valid config on submit", async () => {
    const mockOnSubmit = vi.fn();
    const mockDeployments = [createMockDeployment()];
    const mockStrategies = [createMockStrategy()];

    render(
      <PaperTradingForm
        deployments={mockDeployments}
        strategies={mockStrategies}
        isLoading={false}
        onSubmit={mockOnSubmit}
      />,
    );

    // Select deployment
    const deploymentButton = screen.getByRole("button", { name: /select deployment/i });
    await userEvent.click(deploymentButton);
    await userEvent.click(screen.getByText(mockDeployments[0].name));

    // Select strategy
    const strategyButton = screen.getByRole("button", { name: /select strategy/i });
    await userEvent.click(strategyButton);
    await userEvent.click(screen.getByText(mockStrategies[0].name));

    // Submit form
    const submitButton = screen.getByRole("button", { name: /continue/i });
    await waitFor(() => {
      expect(submitButton).not.toBeDisabled();
    });
    await userEvent.click(submitButton);

    // Verify callback was called with config
    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalled();
      const config = mockOnSubmit.mock.calls[0][0] as PaperTradingConfig;
      expect(config.deployment_id).toBe(mockDeployments[0].id);
      expect(config.strategy_build_id).toBe(mockStrategies[0].id);
      expect(config.initial_equity).toBeGreaterThanOrEqual(1000);
      expect(config.max_leverage).toBeLessThanOrEqual(10);
    });
  });
});
