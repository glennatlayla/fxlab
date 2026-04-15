/**
 * Tests for StrategyDraftForm component.
 *
 * Verifies that:
 *   - All wizard steps are rendered (basics, conditions, risk, parameters, review)
 *   - Step navigation works (next/back buttons)
 *   - Required field validation prevents advancing (e.g., name required on basics step)
 *   - Autosave is called on field change (debounced)
 *   - "blocked paper" badge appears when material uncertainty is unresolved
 *
 * Dependencies:
 *   - vitest for assertions and mocking
 *   - @testing-library/react for render, screen, and user interactions
 *   - @testing-library/user-event for form interaction
 *   - React component: StrategyDraftForm
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { StrategyDraftFormData, UncertaintyEntry } from "@/types/strategy";
import { StrategyDraftForm } from "./StrategyDraftForm";

describe("StrategyDraftForm", () => {
  const mockOnAutosave = vi.fn();
  const mockOnSubmit = vi.fn();

  const initialFormData: StrategyDraftFormData = {
    name: "",
    description: "",
    instrument: "",
    timeframe: "",
    entryCondition: "",
    exitCondition: "",
    maxPositionSize: 10000,
    stopLossPercent: 2,
    takeProfitPercent: 5,
    parameters: [],
  };

  const mockUncertainties: UncertaintyEntry[] = [
    {
      id: "unc-mat-1",
      code: "MATERIAL_AMBIGUITY",
      severity: "material",
      title: "Material Ambiguity",
      description: "Entry signal is ambiguous",
      ownerDisplayName: "Alice",
      resolved: false,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("wizard step rendering", () => {
    it("renders all wizard steps (basics, conditions, risk, parameters, review)", () => {
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      // Step labels appear in the progress indicator bar
      expect(screen.getAllByText(/basics/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/conditions/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/risk/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/parameters/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/review/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("step navigation", () => {
    it("shows step navigation buttons (next/back)", () => {
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      expect(screen.getByRole("button", { name: /next|continue/i })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /back|previous/i })).not.toBeInTheDocument(); // Back button not shown on first step
    });

    it("advances to next step when next button is clicked", async () => {
      const user = userEvent.setup();
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      const nameInput = screen.getByLabelText(/name|strategy name/i);
      const nextButton = screen.getByRole("button", { name: /next|continue/i });

      // Fill in required field
      await user.type(nameInput, "My Strategy");

      // Click next
      await user.click(nextButton);

      // Should now show conditions step
      await waitFor(() => {
        expect(screen.getByLabelText(/entry condition/i)).toBeInTheDocument();
      });
    });

    it("goes back to previous step when back button is clicked", async () => {
      const user = userEvent.setup();
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      const nameInput = screen.getByLabelText(/name|strategy name/i);
      const nextButton = screen.getByRole("button", { name: /next|continue/i });

      await user.type(nameInput, "My Strategy");
      await user.click(nextButton);

      // Wait for back button to appear
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /back|previous/i })).toBeInTheDocument();
      });

      const backButton = screen.getByRole("button", { name: /back|previous/i });
      await user.click(backButton);

      // Should be back to basics step
      expect(screen.getByLabelText(/name|strategy name/i)).toBeInTheDocument();
    });
  });

  describe("field validation", () => {
    it("validates required fields before advancing (name is required on basics step)", async () => {
      const user = userEvent.setup();
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      const nextButton = screen.getByRole("button", { name: /next|continue/i });

      // Try to click next without filling name
      await user.click(nextButton);

      // Should show validation error
      expect(screen.getByText(/name.*required|required.*name/i)).toBeInTheDocument();

      // Should still be on basics step
      expect(screen.getByLabelText(/name|strategy name/i)).toBeInTheDocument();
    });

    it("allows advancing after required fields are filled", async () => {
      const user = userEvent.setup();
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      const nameInput = screen.getByLabelText(/name|strategy name/i);
      const nextButton = screen.getByRole("button", { name: /next|continue/i });

      await user.type(nameInput, "Valid Strategy Name");
      await user.click(nextButton);

      // Should advance to next step
      await waitFor(() => {
        expect(screen.getByLabelText(/entry condition/i)).toBeInTheDocument();
      });
    });
  });

  describe("autosave", () => {
    it("calls onAutosave on field change (debounced)", async () => {
      vi.useFakeTimers();
      const user = userEvent.setup({
        delay: null,
        advanceTimers: vi.advanceTimersByTime,
      });

      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      // Clear any initial mount-triggered autosave
      vi.advanceTimersByTime(1100);
      mockOnAutosave.mockClear();

      const nameInput = screen.getByLabelText(/name|strategy name/i);
      await user.type(nameInput, "A");

      // Autosave should not have been called immediately (debounced)
      expect(mockOnAutosave).not.toHaveBeenCalled();

      // Advance time by debounce delay (1000ms)
      vi.advanceTimersByTime(1100);

      // Now autosave should have been called
      expect(mockOnAutosave).toHaveBeenCalled();

      vi.useRealTimers();
    });

    it("passes current form step to autosave", async () => {
      // Use pre-filled data so we can navigate without typing
      const prefilledData = { ...initialFormData, name: "My Strategy" };
      const user = userEvent.setup();

      render(
        <StrategyDraftForm
          initialData={prefilledData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      // Navigate to conditions step
      const nextButton = screen.getByRole("button", { name: /next|continue/i });
      await user.click(nextButton);

      await waitFor(() => {
        expect(screen.getByLabelText(/entry condition/i)).toBeInTheDocument();
      });

      // Clear all previous autosave calls
      mockOnAutosave.mockClear();

      // Modify a field on the conditions step
      const entryInput = screen.getByLabelText(/entry condition/i);
      await user.type(entryInput, "RSI < 30");

      // Wait for debounced autosave (1000ms debounce + buffer)
      await waitFor(
        () => {
          expect(mockOnAutosave).toHaveBeenCalledWith(
            expect.objectContaining({
              form_step: "conditions",
            }),
          );
        },
        { timeout: 3000 },
      );
    });
  });

  describe("uncertainty blocking", () => {
    it("shows 'blocked paper' badge when material uncertainty is unresolved", () => {
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={mockUncertainties}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      expect(screen.getByText(/blocked|paper|material uncertainty/i)).toBeInTheDocument();
    });

    it("does not show 'blocked paper' badge when all uncertainties are resolved", () => {
      const resolvedUncertainties: UncertaintyEntry[] = [
        {
          ...mockUncertainties[0],
          resolved: true,
          resolutionNote: "Documented and confirmed",
        },
      ];

      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={resolvedUncertainties}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      expect(screen.queryByText(/blocked|paper/i)).not.toBeInTheDocument();
    });

    it("does not show 'blocked paper' badge when no material uncertainties exist", () => {
      const infoUncertainties: UncertaintyEntry[] = [
        {
          id: "unc-info-1",
          code: "LOW_DATA",
          severity: "info",
          title: "Low Confidence",
          description: "Limited data",
          resolved: false,
        },
      ];

      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={infoUncertainties}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      expect(screen.queryByText(/blocked|paper/i)).not.toBeInTheDocument();
    });
  });

  describe("review and submission", () => {
    it("shows submit button on review step", async () => {
      const user = userEvent.setup();

      // Pre-fill name so we can navigate through without validation blocking
      const prefilledData = { ...initialFormData, name: "Complete Strategy" };

      render(
        <StrategyDraftForm
          initialData={prefilledData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      // Step through to review (4 clicks: basics→conditions→risk→parameters→review)
      for (let i = 0; i < 4; i++) {
        const nextButton = screen.getByRole("button", { name: /next|continue/i });
        await user.click(nextButton);
      }

      // Should have submit button on review step
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /submit|create|save.*strategy/i }),
        ).toBeInTheDocument();
      });
    });

    it("calls onSubmit with complete form data when submitting", async () => {
      const user = userEvent.setup();

      // Pre-fill name so we can navigate directly to review
      const prefilledData = { ...initialFormData, name: "Complete Strategy" };

      render(
        <StrategyDraftForm
          initialData={prefilledData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      // Navigate to review step
      for (let i = 0; i < 4; i++) {
        const nextButton = screen.getByRole("button", { name: /next|continue/i });
        await user.click(nextButton);
      }

      // Click submit on review step
      const submitButton = screen.getByRole("button", { name: /submit|create|save.*strategy/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith(
          expect.objectContaining({ name: "Complete Strategy" }),
        );
      });
    });
  });

  describe("step progress indicators", () => {
    it("shows progress indicator for current step", () => {
      render(
        <StrategyDraftForm
          initialData={initialFormData}
          uncertainties={[]}
          onAutosave={mockOnAutosave}
          onSubmit={mockOnSubmit}
        />,
      );

      // On basics step, should show step progress text
      expect(screen.getByText(/step 1 of 5/i)).toBeInTheDocument();
    });
  });
});
