/**
 * Unit tests for BacktestForm component (FE-08).
 *
 * Covers form rendering, validation, and core interactions.
 * Uses React Testing Library for behavior-focused assertions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { BacktestForm } from "../components/BacktestForm";

// Mock the API
vi.mock("../api", () => ({
  backtestApi: {
    submitBacktest: vi.fn(),
  },
}));

vi.mock("@/features/strategy/api", () => ({
  strategyApi: {
    listStrategies: vi.fn(),
  },
}));

// Create a wrapper component with necessary providers
function renderWithProviders(component: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{component}</BrowserRouter>
    </QueryClientProvider>,
  );
}

describe("BacktestForm", () => {
  const mockOnSubmit = vi.fn();
  const mockOnError = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("rendering", () => {
    it("renders all form fields", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // Check for all major form sections using getByRole for precision
      expect(screen.getByLabelText(/strategy/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/symbols?/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/start date/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/end date/i)).toBeInTheDocument();
      expect(screen.getByText(/interval/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/initial equity/i)).toBeInTheDocument();
    });

    it("renders the submit button", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      expect(screen.getByRole("button", { name: /run backtest/i })).toBeInTheDocument();
    });

    it("renders advanced settings section", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      expect(screen.getByRole("button", { name: /advanced settings/i })).toBeInTheDocument();
    });

    it("initializes with default interval value (1d)", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const oneDayRadio = screen.getByRole("radio", { name: "1d" });
      expect(oneDayRadio).toHaveAttribute("aria-pressed", "true");
    });

    it("submit button is disabled when form is empty", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const submitButton = screen.getByRole("button", { name: /run backtest/i });
      expect(submitButton).toBeDisabled();
    });
  });

  describe("field labels", () => {
    it("has proper labels for all critical fields", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // Verify labels exist and are associated with inputs
      const strategyButton = screen.getByLabelText(/strategy/i);
      expect(strategyButton).toBeInTheDocument();

      const startDateInput = screen.getByLabelText(/start date/i);
      expect(startDateInput).toBeInTheDocument();

      const endDateInput = screen.getByLabelText(/end date/i);
      expect(endDateInput).toBeInTheDocument();

      const equityInput = screen.getByLabelText(/initial equity/i);
      expect(equityInput).toBeInTheDocument();
    });

    it("marks required fields with asterisk", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // All main fields should have required marker
      const requiredMarkers = screen.getAllByText("*");
      expect(requiredMarkers.length).toBeGreaterThan(0);
    });
  });

  describe("date input fields", () => {
    it("has date input fields for start and end dates", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const startDateInput = screen.getByLabelText(/start date/i) as HTMLInputElement;
      const endDateInput = screen.getByLabelText(/end date/i) as HTMLInputElement;

      expect(startDateInput.type).toBe("date");
      expect(endDateInput.type).toBe("date");
    });
  });

  describe("interval selector", () => {
    it("provides all time interval options", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // Check that all interval options are rendered
      const intervals = ["1m", "5m", "15m", "1h", "4h", "1d"];
      for (const interval of intervals) {
        expect(screen.getByRole("radio", { name: interval })).toBeInTheDocument();
      }
    });
  });

  describe("picker buttons", () => {
    it("has strategy picker button", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // Find button for strategy selection
      const buttons = screen.getAllByRole("button");
      const strategyButton = buttons.find((btn) => btn.textContent?.includes("Select strategy"));
      expect(strategyButton).toBeInTheDocument();
    });

    it("has symbol picker button", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // Find button for symbol selection
      const buttons = screen.getAllByRole("button");
      const symbolButton = buttons.find((btn) => btn.textContent?.includes("Select symbols"));
      expect(symbolButton).toBeInTheDocument();
    });
  });

  describe("equity input", () => {
    it("has numeric input for initial equity", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const equityInput = screen.getByLabelText(/initial equity/i) as HTMLInputElement;
      expect(equityInput.type).toBe("number");
      expect(equityInput.min).toBe("100");
      expect(equityInput.max).toBe("10000000");
    });

    it("displays equity constraints help text", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      // Should show min/max help text
      expect(screen.getByText(/Min:.*100.*Max:.*10.*000.*000/)).toBeInTheDocument();
    });
  });

  describe("advanced settings", () => {
    it("has expandable advanced settings section", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const advancedButton = screen.getByRole("button", { name: /advanced settings/i });
      expect(advancedButton).toBeInTheDocument();
    });
  });

  describe("form structure", () => {
    it("is wrapped in a proper form element", () => {
      const { container: _container } = renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const form = _container.querySelector("form");
      expect(form).toBeInTheDocument();
      expect(form?.noValidate).toBe(true);
    });

    it("has a submit button at the bottom of the form", () => {
      renderWithProviders(
        <BacktestForm onSubmit={mockOnSubmit} onError={mockOnError} />,
      );

      const submitButton = screen.getByRole("button", { name: /run backtest/i });
      expect(submitButton).toBeInTheDocument();
      // Check if it has fixed positioning styles
      expect(submitButton.className).toContain("fixed");
    });
  });
});
