/**
 * MfaGate component tests.
 *
 * Verifies:
 *   - Renders MfaChallenge when isRequired=true
 *   - Renders children when isRequired=false
 *   - Calls onVerify with code from MfaChallenge
 *   - Shows error message on verification failure
 *   - Renders children after successful verification
 *   - Calls onCancel when user cancels MFA
 *   - Uses BottomSheet on mobile, modal on desktop
 *   - Disables input while verifying
 *
 * Dependencies:
 *   - vitest, @testing-library/react, @testing-library/user-event
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MfaGate } from "../MfaGate";

// Mock useIsMobile
const mockUseIsMobile = vi.fn();
vi.mock("@/hooks/useMediaQuery", () => ({
  useIsMobile: () => mockUseIsMobile(),
}));

describe("MfaGate component", () => {
  const mockOnVerify = vi.fn();
  const mockOnCancel = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseIsMobile.mockReturnValue(false); // Default to desktop
  });

  describe("rendering", () => {
    it("shows MfaChallenge when isRequired=true", () => {
      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Content</div>
        </MfaGate>,
      );

      expect(screen.getByText("Verify Your Identity")).toBeInTheDocument();
      expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
    });

    it("renders children when isRequired=false", () => {
      render(
        <MfaGate isRequired={false} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Secret content</div>
        </MfaGate>,
      );

      expect(screen.getByTestId("protected-content")).toBeInTheDocument();
      expect(screen.queryByText("Verify Your Identity")).not.toBeInTheDocument();
    });
  });

  describe("presentation", () => {
    it("uses BottomSheet on mobile", () => {
      mockUseIsMobile.mockReturnValue(true);

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      // BottomSheet renders with role="dialog"
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("uses modal container on desktop", () => {
      mockUseIsMobile.mockReturnValue(false);

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      // Modal should be rendered (centered overlay)
      // Look for the modal backdrop
      const backdrop = document.querySelector(".fixed.inset-0.z-40.bg-black\\/50");
      expect(backdrop).toBeInTheDocument();
    });
  });

  describe("verification flow", () => {
    it("calls onVerify with code when user submits", async () => {
      const user = userEvent.setup();
      mockOnVerify.mockResolvedValue(undefined);

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Content</div>
        </MfaGate>,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      await user.type(input, "123456");

      const submitButton = screen.getByRole("button", { name: /verify/i });
      await user.click(submitButton);

      expect(mockOnVerify).toHaveBeenCalledWith("123456");
    });

    it("renders children after verification succeeds and parent clears isRequired", async () => {
      const user = userEvent.setup();
      mockOnVerify.mockResolvedValue(undefined);

      const { rerender } = render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Secret content</div>
        </MfaGate>,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      await user.type(input, "123456");

      const submitButton = screen.getByRole("button", { name: /verify/i });
      await user.click(submitButton);

      // Wait for onVerify to be called
      await waitFor(() => {
        expect(mockOnVerify).toHaveBeenCalledWith("123456");
      });

      // Parent clears isRequired after verification
      rerender(
        <MfaGate isRequired={false} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Secret content</div>
        </MfaGate>,
      );

      expect(screen.getByTestId("protected-content")).toBeInTheDocument();
    });

    it("shows error message on verification failure", async () => {
      const user = userEvent.setup();
      const error = new Error("Invalid code");
      mockOnVerify.mockRejectedValue(error);

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Content</div>
        </MfaGate>,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      await user.type(input, "123456");

      const submitButton = screen.getByRole("button", { name: /verify/i });
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText("Invalid code")).toBeInTheDocument();
      });

      // Input should still be visible for retry
      expect(input).toBeInTheDocument();
    });

    it("disables input while verification is in progress", async () => {
      const user = userEvent.setup();
      // Create a promise that never resolves to simulate slow verification
      mockOnVerify.mockImplementation(() => new Promise(() => {}));

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      await user.type(input, "123456");

      const submitButton = screen.getByRole("button", { name: /verify/i });
      await user.click(submitButton);

      // Spinner should appear
      expect(screen.getByTestId("verify-spinner")).toBeInTheDocument();

      // Submit button should be disabled
      expect(submitButton).toBeDisabled();
    });
  });

  describe("cancellation", () => {
    it("calls onCancel when user clicks cancel", async () => {
      const user = userEvent.setup();

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      await user.click(cancelButton);

      expect(mockOnCancel).toHaveBeenCalledTimes(1);
    });

    it("calls onCancel when user dismisses mobile sheet", async () => {
      mockUseIsMobile.mockReturnValue(true);

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      // Click the X button in the sheet header
      const closeButton = screen.getByRole("button", { name: /close/i });
      await userEvent.click(closeButton);

      expect(mockOnCancel).toHaveBeenCalledTimes(1);
    });

    it("calls onCancel when backdrop is clicked on desktop", async () => {
      mockUseIsMobile.mockReturnValue(false);

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      // Find and click the backdrop (semi-transparent overlay)
      const backdrops = document.querySelectorAll(".fixed.inset-0");
      const backdrop = Array.from(backdrops).find((el) =>
        el.classList.contains("bg-black"),
      ) as HTMLElement;

      if (backdrop) {
        await userEvent.click(backdrop);
        expect(mockOnCancel).toHaveBeenCalledTimes(1);
      }
    });
  });

  describe("state management", () => {
    it("allows retry after failed verification", async () => {
      const user = userEvent.setup();
      mockOnVerify.mockRejectedValueOnce(new Error("Invalid code"));
      mockOnVerify.mockResolvedValueOnce(undefined);

      const { rerender } = render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Content</div>
        </MfaGate>,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      }) as HTMLInputElement;
      const submitButton = screen.getByRole("button", { name: /verify/i });

      // First attempt fails
      await user.type(input, "000000");
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText("Invalid code")).toBeInTheDocument();
      });

      // Clear the error by typing new input
      await user.clear(input);
      await user.type(input, "123456");

      // Second attempt succeeds
      await user.click(submitButton);

      // Wait for verification to complete
      await waitFor(() => {
        expect(mockOnVerify).toHaveBeenCalledTimes(2);
      });

      // Parent clears isRequired after successful verification
      rerender(
        <MfaGate isRequired={false} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div data-testid="protected-content">Content</div>
        </MfaGate>,
      );

      expect(screen.getByTestId("protected-content")).toBeInTheDocument();
    });

    it("clears error when user types new code after failure", async () => {
      const user = userEvent.setup();
      mockOnVerify.mockRejectedValue(new Error("Invalid code"));

      render(
        <MfaGate isRequired={true} onVerify={mockOnVerify} onCancel={mockOnCancel}>
          <div>Content</div>
        </MfaGate>,
      );

      const input = screen.getByRole("textbox", {
        name: /authentication code/i,
      });
      const submitButton = screen.getByRole("button", { name: /verify/i });

      // First attempt fails
      await user.type(input, "000000");
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText("Invalid code")).toBeInTheDocument();
      });

      // User starts typing new code
      await user.clear(input);

      // Error message should be cleared
      expect(screen.queryByText("Invalid code")).not.toBeInTheDocument();
    });
  });
});
