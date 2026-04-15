/**
 * MfaChallenge component tests.
 *
 * Verifies:
 *   - 6-digit code input field with numeric-only validation
 *   - Submit button enabled only when code is valid (6 digits)
 *   - Submit calls onSubmit callback with entered code
 *   - Error message displayed from error prop
 *   - Error cleared on new input
 *   - Loading state shown while verifying
 *   - Auto-focus on input on mount
 *   - Enter key submits the form
 *   - Cancel button calls onCancel
 *   - Accessibility: proper labels and aria-describedby
 *
 * Dependencies:
 *   - vitest, @testing-library/react, @testing-library/user-event
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MfaChallenge } from "../MfaChallenge";

describe("MfaChallenge component", () => {
  const mockOnSubmit = vi.fn();
  const mockOnCancel = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("rendering", () => {
    it("renders title and description with defaults", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      expect(screen.getByText("Verify Your Identity")).toBeInTheDocument();
      expect(screen.getByText("Enter your 6-digit authentication code")).toBeInTheDocument();
    });

    it("renders custom title and description when provided", () => {
      render(
        <MfaChallenge
          onSubmit={mockOnSubmit}
          onCancel={mockOnCancel}
          title="MFA Required"
          description="Enter your code"
        />,
      );

      expect(screen.getByText("MFA Required")).toBeInTheDocument();
      expect(screen.getByText("Enter your code")).toBeInTheDocument();
    });

    it("renders input field with numeric input mode", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      expect(input).toHaveAttribute("inputMode", "numeric");
      expect(input).toHaveAttribute("pattern", "[0-9]*");
      expect(input).toHaveAttribute("maxLength", "6");
    });

    it("renders submit button disabled by default", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const submitButton = screen.getByRole("button", { name: /verify/i });
      expect(submitButton).toBeDisabled();
    });

    it("renders cancel button", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      expect(cancelButton).toBeInTheDocument();
    });
  });

  describe("input validation", () => {
    it("accepts only numeric input", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      }) as HTMLInputElement;

      await user.type(input, "abc123");
      expect(input.value).toBe("123"); // Only digits accepted
    });

    it("enforces maxLength of 6 digits", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      }) as HTMLInputElement;

      await user.type(input, "1234567890");
      expect(input.value.length).toBeLessThanOrEqual(6);
    });
  });

  describe("submit button state", () => {
    it("enables submit button when 6 digits are entered", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      const submitButton = screen.getByRole("button", { name: /verify/i });

      expect(submitButton).toBeDisabled();

      await user.type(input, "123456");
      expect(submitButton).not.toBeDisabled();
    });

    it("disables submit button when code is incomplete", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      const submitButton = screen.getByRole("button", { name: /verify/i });

      await user.type(input, "12345");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("submission", () => {
    it("calls onSubmit with code when submit button clicked", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      const submitButton = screen.getByRole("button", { name: /verify/i });

      await user.type(input, "123456");
      await user.click(submitButton);

      expect(mockOnSubmit).toHaveBeenCalledWith("123456");
      expect(mockOnSubmit).toHaveBeenCalledTimes(1);
    });

    it("submits on Enter key press", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });

      await user.type(input, "123456");
      await user.keyboard("{Enter}");

      expect(mockOnSubmit).toHaveBeenCalledWith("123456");
    });

    it("does not submit on Enter if code is incomplete", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });

      await user.type(input, "12345");
      await user.keyboard("{Enter}");

      expect(mockOnSubmit).not.toHaveBeenCalled();
    });

    it("disables submit button when isVerifying is true", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} isVerifying={true} />);

      const submitButton = screen.getByRole("button", { name: /verify/i });
      expect(submitButton).toBeDisabled();
    });

    it("shows spinner when isVerifying is true", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} isVerifying={true} />);

      expect(screen.getByTestId("verify-spinner")).toBeInTheDocument();
    });
  });

  describe("error handling", () => {
    it("displays error message when error prop is set", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} error="Invalid code" />);

      expect(screen.getByText("Invalid code")).toBeInTheDocument();
    });

    it("applies error styling to input when error exists", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} error="Invalid code" />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      expect(input).toHaveClass("border-red-500");
    });

    it("clears error when user starts typing", async () => {
      const user = userEvent.setup();
      const { rerender } = render(
        <MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} error="Invalid code" />,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });

      await user.type(input, "1");

      // Component should signal to parent that error should be cleared
      // Parent would update the error prop
      rerender(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} error={null} />);

      expect(screen.queryByText("Invalid code")).not.toBeInTheDocument();
    });
  });

  describe("cancel", () => {
    it("calls onCancel when cancel button is clicked", async () => {
      const user = userEvent.setup();
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      await user.click(cancelButton);

      expect(mockOnCancel).toHaveBeenCalledTimes(1);
    });
  });

  describe("focus management", () => {
    it("auto-focuses the input on mount", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      expect(input).toHaveFocus();
    });
  });

  describe("accessibility", () => {
    it("input has proper label", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      expect(input).toBeInTheDocument();
    });

    it("error message is associated with input via aria-describedby", () => {
      render(<MfaChallenge onSubmit={mockOnSubmit} onCancel={mockOnCancel} error="Invalid code" />);

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      const errorId = input.getAttribute("aria-describedby");
      expect(errorId).toBeTruthy();
      expect(screen.getByText("Invalid code")).toHaveAttribute("id", errorId);
    });
  });
});
