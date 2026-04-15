/**
 * Tests for DslEditor component (M10).
 *
 * Verifies:
 *   - Renders label and textarea with correct placeholder.
 *   - Calls onChange when user types.
 *   - Triggers debounced DSL validation on value change.
 *   - Displays "Validating..." indicator during validation.
 *   - Displays "Valid" badge when DSL is valid.
 *   - Displays error count and error details when DSL is invalid.
 *   - Shows detected indicators and variables for valid expressions.
 *   - Auto-completion dropdown appears when typing indicator prefix.
 *   - Selecting a completion replaces the partial word.
 *   - Line numbers gutter renders correct number of lines.
 *   - Disabled state prevents editing.
 *   - Empty input clears validation state.
 *
 * Dependencies:
 *   - vitest for assertions and mocking.
 *   - @testing-library/react for render, screen, user interactions.
 *   - @testing-library/user-event for typing simulation.
 *   - React component: DslEditor.
 *
 * Example:
 *   npx vitest run src/components/DslEditor.test.tsx
 */

import React from "react";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DslEditor } from "./DslEditor";
import type { DslValidationResult } from "@/features/strategy/api";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockValidateDsl = vi.fn<[string], Promise<DslValidationResult>>();

vi.mock("@/features/strategy/api", () => ({
  strategyApi: {
    validateDsl: (expression: string) => mockValidateDsl(expression),
  },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_RESULT: DslValidationResult = {
  is_valid: true,
  errors: [],
  indicators_used: ["RSI", "SMA"],
  variables_used: ["price"],
};

const INVALID_RESULT: DslValidationResult = {
  is_valid: false,
  errors: [
    {
      message: "RSI requires 1 argument, got 0",
      line: 1,
      column: 1,
      suggestion: "Use RSI(period), e.g., RSI(14)",
    },
  ],
  indicators_used: [],
  variables_used: [],
};

const MULTI_ERROR_RESULT: DslValidationResult = {
  is_valid: false,
  errors: [
    { message: "Unknown indicator FOOBAR", line: 1, column: 1, suggestion: null },
    { message: "Expected comparison operator", line: 1, column: 12, suggestion: null },
  ],
  indicators_used: [],
  variables_used: [],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderEditor(props: Partial<React.ComponentProps<typeof DslEditor>> = {}) {
  const defaultProps = {
    value: "",
    onChange: vi.fn(),
    label: "Entry Condition",
    testId: "test-dsl",
  };
  return render(<DslEditor {...defaultProps} {...props} />);
}

/**
 * Advance fake timers past the debounce delay and flush the resolved promise.
 *
 * advanceTimersByTimeAsync fires the setTimeout callback AND flushes the
 * microtask queue so resolved promises settle within the same act() boundary.
 * Do NOT combine with waitFor — waitFor's internal polling uses setTimeout
 * which is also faked, causing infinite hangs.
 */
async function advanceValidation(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DslEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    mockValidateDsl.mockResolvedValue(VALID_RESULT);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ---- Rendering ----

  describe("rendering", () => {
    it("renders label and textarea", () => {
      renderEditor({ label: "Entry Condition" });

      expect(screen.getByText("Entry Condition")).toBeInTheDocument();
      expect(screen.getByTestId("test-dsl-textarea")).toBeInTheDocument();
    });

    it("renders placeholder text", () => {
      renderEditor({ placeholder: "e.g., RSI(14) < 30" });

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea).toHaveAttribute("placeholder", "e.g., RSI(14) < 30");
    });

    it("renders default placeholder when none provided", () => {
      renderEditor();

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea).toHaveAttribute("placeholder", "e.g., RSI(14) < 30 AND price > SMA(200)");
    });

    it("renders line numbers gutter", () => {
      renderEditor();

      expect(screen.getByTestId("test-dsl-line-numbers")).toBeInTheDocument();
    });

    it("renders minimum 3 line numbers for empty input", () => {
      renderEditor({ value: "" });

      const gutter = screen.getByTestId("test-dsl-line-numbers");
      expect(gutter.textContent).toContain("1");
      expect(gutter.textContent).toContain("2");
      expect(gutter.textContent).toContain("3");
    });

    it("renders correct number of line numbers for multiline input", () => {
      renderEditor({ value: "line1\nline2\nline3\nline4\nline5" });

      const gutter = screen.getByTestId("test-dsl-line-numbers");
      expect(gutter.textContent).toContain("5");
    });

    it("displays the current value in the textarea", () => {
      renderEditor({ value: "RSI(14) < 30" });

      const textarea = screen.getByTestId("test-dsl-textarea") as HTMLTextAreaElement;
      expect(textarea.value).toBe("RSI(14) < 30");
    });
  });

  // ---- Disabled state ----

  describe("disabled state", () => {
    it("disables textarea when disabled prop is true", () => {
      renderEditor({ disabled: true });

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea).toBeDisabled();
    });

    it("textarea is enabled by default", () => {
      renderEditor();

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea).not.toBeDisabled();
    });
  });

  // ---- onChange callback ----

  describe("onChange callback", () => {
    it("calls onChange when user types", async () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      await userEvent.type(textarea, "R");

      expect(onChange).toHaveBeenCalledWith("R");
    });
  });

  // ---- Validation ----

  describe("validation", () => {
    it("shows validating indicator during validation", async () => {
      // Keep the promise pending so we observe the intermediate validating state
      let resolveValidation!: (value: DslValidationResult) => void;
      mockValidateDsl.mockImplementation(
        () =>
          new Promise<DslValidationResult>((resolve) => {
            resolveValidation = resolve;
          }),
      );

      renderEditor({ value: "RSI(14) < 30" });

      // Synchronous advance: fires the setTimeout callback but keeps the promise pending
      act(() => {
        vi.advanceTimersByTime(600);
      });

      expect(screen.getByTestId("test-dsl-validating")).toBeInTheDocument();
      expect(screen.getByText("Validating...")).toBeInTheDocument();

      // Clean up: resolve the pending promise to avoid act() warnings
      await act(async () => {
        resolveValidation(VALID_RESULT);
      });
    });

    it("displays Valid badge when DSL validates successfully", async () => {
      mockValidateDsl.mockResolvedValue(VALID_RESULT);
      renderEditor({ value: "RSI(14) < 30" });

      await advanceValidation();

      expect(screen.getByTestId("test-dsl-valid")).toBeInTheDocument();
      expect(screen.getByText("Valid")).toBeInTheDocument();
    });

    it("displays error count when DSL is invalid", async () => {
      mockValidateDsl.mockResolvedValue(INVALID_RESULT);
      renderEditor({ value: "RSI() < 30" });

      await advanceValidation();

      expect(screen.getByTestId("test-dsl-invalid")).toBeInTheDocument();
      expect(screen.getByText("1 error")).toBeInTheDocument();
    });

    it("displays plural error count for multiple errors", async () => {
      mockValidateDsl.mockResolvedValue(MULTI_ERROR_RESULT);
      renderEditor({ value: "FOOBAR invalid" });

      await advanceValidation();

      expect(screen.getByText("2 errors")).toBeInTheDocument();
    });

    it("displays error details with line and column", async () => {
      mockValidateDsl.mockResolvedValue(INVALID_RESULT);
      renderEditor({ value: "RSI() < 30" });

      await advanceValidation();

      const errors = screen.getByTestId("test-dsl-errors");
      expect(errors).toBeInTheDocument();

      const errorItem = screen.getByTestId("test-dsl-error-0");
      expect(errorItem).toHaveTextContent("Line 1, Col 1:");
      expect(errorItem).toHaveTextContent("RSI requires 1 argument, got 0");
    });

    it("displays suggestion when available in error", async () => {
      mockValidateDsl.mockResolvedValue(INVALID_RESULT);
      renderEditor({ value: "RSI() < 30" });

      await advanceValidation();

      const errorItem = screen.getByTestId("test-dsl-error-0");
      expect(errorItem).toHaveTextContent("Use RSI(period), e.g., RSI(14)");
    });

    it("does not validate empty input", async () => {
      renderEditor({ value: "" });

      await advanceValidation();

      expect(mockValidateDsl).not.toHaveBeenCalled();
    });

    it("does not validate whitespace-only input", async () => {
      renderEditor({ value: "   " });

      await advanceValidation();

      expect(mockValidateDsl).not.toHaveBeenCalled();
    });

    it("debounces validation calls", async () => {
      const { rerender } = renderEditor({ value: "R" });

      // Advance partway — not enough to fire debounce
      act(() => {
        vi.advanceTimersByTime(200);
      });

      rerender(<DslEditor value="RS" onChange={vi.fn()} label="Entry" testId="test-dsl" />);

      act(() => {
        vi.advanceTimersByTime(200);
      });

      rerender(<DslEditor value="RSI" onChange={vi.fn()} label="Entry" testId="test-dsl" />);

      // Now advance past full debounce for the final value
      await advanceValidation();

      // Only the final value should be validated
      expect(mockValidateDsl).toHaveBeenCalledTimes(1);
      expect(mockValidateDsl).toHaveBeenCalledWith("RSI");
    });

    it("silently handles validation API errors", async () => {
      mockValidateDsl.mockRejectedValue(new Error("Network failure"));
      renderEditor({ value: "RSI(14) < 30" });

      await advanceValidation();

      // No crash — validation state cleared
      expect(screen.queryByTestId("test-dsl-errors")).not.toBeInTheDocument();
      expect(screen.queryByTestId("test-dsl-valid")).not.toBeInTheDocument();
      expect(screen.queryByTestId("test-dsl-invalid")).not.toBeInTheDocument();
    });
  });

  // ---- Indicator / variable badges ----

  describe("metadata display", () => {
    it("displays indicator badges for valid expression", async () => {
      mockValidateDsl.mockResolvedValue(VALID_RESULT);
      renderEditor({ value: "RSI(14) < 30 AND price > SMA(200)" });

      await advanceValidation();

      expect(screen.getByTestId("test-dsl-metadata")).toBeInTheDocument();
      expect(screen.getByTestId("test-dsl-indicator-RSI")).toHaveTextContent("RSI");
      expect(screen.getByTestId("test-dsl-indicator-SMA")).toHaveTextContent("SMA");
    });

    it("displays variable badges for valid expression", async () => {
      mockValidateDsl.mockResolvedValue(VALID_RESULT);
      renderEditor({ value: "price > SMA(200)" });

      await advanceValidation();

      expect(screen.getByTestId("test-dsl-variable-price")).toHaveTextContent("price");
    });

    it("does not display metadata for invalid expression", async () => {
      mockValidateDsl.mockResolvedValue(INVALID_RESULT);
      renderEditor({ value: "RSI() < 30" });

      await advanceValidation();

      expect(screen.queryByTestId("test-dsl-metadata")).not.toBeInTheDocument();
    });
  });

  // ---- Auto-completion ----
  // These tests use real timers because auto-completion is synchronous state
  // driven by handleChange, not by the debounced validation timer.

  describe("auto-completion", () => {
    it("shows completion dropdown when typing an indicator prefix", async () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      fireEvent.change(textarea, { target: { value: "RS", selectionStart: 2 } });

      await waitFor(() => {
        expect(screen.getByTestId("test-dsl-completions")).toBeInTheDocument();
      });
    });

    it("shows RSI in completions when typing RS", async () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      fireEvent.change(textarea, { target: { value: "RS", selectionStart: 2 } });

      await waitFor(() => {
        expect(screen.getByTestId("test-dsl-completion-RSI")).toBeInTheDocument();
      });
    });

    it("does not show completions for single character", () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      fireEvent.change(textarea, { target: { value: "R", selectionStart: 1 } });

      expect(screen.queryByTestId("test-dsl-completions")).not.toBeInTheDocument();
    });

    it("applies completion when item is clicked", async () => {
      vi.useRealTimers();
      // Use a stateful wrapper so the value prop tracks user input —
      // applyCompletion reads the prop value to locate the partial word,
      // and jsdom resets selectionStart on controlled re-renders.
      let capturedValue = "";
      function StatefulEditor() {
        const [val, setVal] = React.useState("");
        return (
          <DslEditor
            value={val}
            onChange={(v) => {
              setVal(v);
              capturedValue = v;
            }}
            label="Entry"
            testId="test-dsl"
          />
        );
      }
      render(<StatefulEditor />);

      const textarea = screen.getByTestId("test-dsl-textarea");
      // Simulate typing "RS" — triggers completion dropdown
      fireEvent.change(textarea, { target: { value: "RS", selectionStart: 2 } });

      await waitFor(() => {
        expect(screen.getByTestId("test-dsl-completion-RSI")).toBeInTheDocument();
      });

      // Click the RSI completion via mouseDown (prevents textarea blur)
      fireEvent.mouseDown(screen.getByTestId("test-dsl-completion-RSI"));

      // The component should have replaced "RS" with "RSI"
      expect(capturedValue).toBe("RSI");
    });

    it("hides completions on textarea blur", async () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      fireEvent.change(textarea, { target: { value: "RS", selectionStart: 2 } });

      await waitFor(() => {
        expect(screen.getByTestId("test-dsl-completions")).toBeInTheDocument();
      });

      fireEvent.blur(textarea);

      expect(screen.queryByTestId("test-dsl-completions")).not.toBeInTheDocument();
    });

    it("shows variable completions for matching prefix", async () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      fireEvent.change(textarea, { target: { value: "pr", selectionStart: 2 } });

      await waitFor(() => {
        expect(screen.getByTestId("test-dsl-completion-price")).toBeInTheDocument();
      });
    });

    it("shows keyword completions for matching prefix", async () => {
      vi.useRealTimers();
      const onChange = vi.fn();
      renderEditor({ onChange });

      const textarea = screen.getByTestId("test-dsl-textarea");
      fireEvent.change(textarea, { target: { value: "AN", selectionStart: 2 } });

      await waitFor(() => {
        expect(screen.getByTestId("test-dsl-completion-AND")).toBeInTheDocument();
      });
    });
  });

  // ---- Border color styling ----

  describe("border styling", () => {
    it("applies green border when valid", async () => {
      mockValidateDsl.mockResolvedValue(VALID_RESULT);
      renderEditor({ value: "RSI(14) < 30" });

      await advanceValidation();

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea.className).toContain("border-green-400");
    });

    it("applies red border when invalid", async () => {
      mockValidateDsl.mockResolvedValue(INVALID_RESULT);
      renderEditor({ value: "RSI() < 30" });

      await advanceValidation();

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea.className).toContain("border-red-400");
    });

    it("applies neutral border when no validation result", () => {
      renderEditor({ value: "" });

      const textarea = screen.getByTestId("test-dsl-textarea");
      expect(textarea.className).toContain("border-surface-300");
    });
  });

  // ---- testId customisation ----

  describe("testId prop", () => {
    it("uses custom testId prefix", () => {
      renderEditor({ testId: "custom-editor" });

      expect(screen.getByTestId("custom-editor")).toBeInTheDocument();
      expect(screen.getByTestId("custom-editor-textarea")).toBeInTheDocument();
      expect(screen.getByTestId("custom-editor-line-numbers")).toBeInTheDocument();
    });
  });
});
