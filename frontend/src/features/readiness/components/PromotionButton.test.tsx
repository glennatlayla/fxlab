/**
 * Tests for PromotionButton component.
 *
 * AC-3: "Submit for promotion" is absent (not merely disabled) when grade is F.
 * Covers: trigger button, rationale form, validation, cancel, confirm, grade gating.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PromotionButton } from "./PromotionButton";

describe("PromotionButton", () => {
  const defaultProps = {
    grade: "B" as const,
    hasPendingPromotion: false,
    runId: "run-1",
    onSubmit: vi.fn(),
  };

  // -------------------------------------------------------------------------
  // Trigger button (collapsed state)
  // -------------------------------------------------------------------------

  it("renders submit button for non-F grades", () => {
    render(<PromotionButton {...defaultProps} />);
    expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeInTheDocument();
  });

  it("does NOT render at all when grade is F", () => {
    render(<PromotionButton {...defaultProps} grade="F" />);
    expect(screen.queryByRole("button", { name: /submit for promotion/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId("promotion-button-container")).not.toBeInTheDocument();
  });

  it("is disabled when a pending promotion exists", () => {
    render(<PromotionButton {...defaultProps} hasPendingPromotion={true} />);
    const btn = screen.getByRole("button", { name: /submit for promotion/i });
    expect(btn).toBeDisabled();
  });

  it("shows pending label when promotion is pending", () => {
    render(<PromotionButton {...defaultProps} hasPendingPromotion={true} />);
    expect(screen.getByText(/pending/i)).toBeInTheDocument();
  });

  it("renders for grade A", () => {
    render(<PromotionButton {...defaultProps} grade="A" />);
    expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeInTheDocument();
  });

  it("renders for grade C", () => {
    render(<PromotionButton {...defaultProps} grade="C" />);
    expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeInTheDocument();
  });

  it("renders for grade D", () => {
    render(<PromotionButton {...defaultProps} grade="D" />);
    expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Rationale form (expanded state)
  // -------------------------------------------------------------------------

  it("opens rationale form on button click", () => {
    render(<PromotionButton {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    expect(screen.getByTestId("promotion-rationale-input")).toBeInTheDocument();
    expect(screen.getByTestId("promotion-target-stage-select")).toBeInTheDocument();
    expect(screen.getByTestId("promotion-confirm-button")).toBeInTheDocument();
    expect(screen.getByTestId("promotion-cancel-button")).toBeInTheDocument();
  });

  it("disables confirm button when rationale is too short", () => {
    render(<PromotionButton {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    // Empty rationale — confirm should be disabled.
    expect(screen.getByTestId("promotion-confirm-button")).toBeDisabled();

    // Type a short rationale (under 10 chars).
    fireEvent.change(screen.getByTestId("promotion-rationale-input"), {
      target: { value: "short" },
    });
    expect(screen.getByTestId("promotion-confirm-button")).toBeDisabled();
  });

  it("enables confirm button when rationale meets minimum length", () => {
    render(<PromotionButton {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    fireEvent.change(screen.getByTestId("promotion-rationale-input"), {
      target: { value: "Strong OOS performance across all regimes" },
    });
    expect(screen.getByTestId("promotion-confirm-button")).not.toBeDisabled();
  });

  it("calls onSubmit with rationale and target stage on confirm", () => {
    const onSubmit = vi.fn();
    render(<PromotionButton {...defaultProps} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    fireEvent.change(screen.getByTestId("promotion-rationale-input"), {
      target: { value: "Strong OOS performance across all regimes" },
    });
    fireEvent.change(screen.getByTestId("promotion-target-stage-select"), {
      target: { value: "live" },
    });
    fireEvent.click(screen.getByTestId("promotion-confirm-button"));

    expect(onSubmit).toHaveBeenCalledWith("Strong OOS performance across all regimes", "live");
  });

  it("closes form and resets on cancel", () => {
    render(<PromotionButton {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    // Type something then cancel.
    fireEvent.change(screen.getByTestId("promotion-rationale-input"), {
      target: { value: "some rationale" },
    });
    fireEvent.click(screen.getByTestId("promotion-cancel-button"));

    // Form should be closed; trigger button visible again.
    expect(screen.queryByTestId("promotion-rationale-input")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeInTheDocument();
  });

  it("defaults target stage to paper", () => {
    render(<PromotionButton {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    const select = screen.getByTestId("promotion-target-stage-select") as HTMLSelectElement;
    expect(select.value).toBe("paper");
  });

  it("shows character count relative to minimum", () => {
    render(<PromotionButton {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /submit for promotion/i }));

    expect(screen.getByText("0/10 characters minimum")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("promotion-rationale-input"), {
      target: { value: "1234567" },
    });
    expect(screen.getByText("7/10 characters minimum")).toBeInTheDocument();
  });

  it("disables form inputs while submitting", () => {
    render(<PromotionButton {...defaultProps} isSubmitting={true} />);
    // When isSubmitting and form is not yet open, the trigger button should be disabled.
    // (The parent re-renders with isSubmitting=true after confirm click.)
    expect(screen.getByRole("button", { name: /submit for promotion/i })).toBeDisabled();
  });
});
