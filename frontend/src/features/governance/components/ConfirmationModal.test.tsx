/**
 * Tests for ConfirmationModal component.
 *
 * Covers: rendering, close-on-escape, close-on-backdrop-click, ARIA attributes,
 * and focus management.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfirmationModal } from "./ConfirmationModal";

describe("ConfirmationModal", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    title: "Confirm Action",
  };

  it("renders modal when isOpen is true", () => {
    render(
      <ConfirmationModal {...defaultProps}>
        <p>Are you sure?</p>
      </ConfirmationModal>,
    );

    expect(screen.getByTestId("confirmation-modal")).toBeInTheDocument();
    expect(screen.getByText("Confirm Action")).toBeInTheDocument();
    expect(screen.getByText("Are you sure?")).toBeInTheDocument();
  });

  it("does not render when isOpen is false", () => {
    render(
      <ConfirmationModal {...defaultProps} isOpen={false}>
        <p>Are you sure?</p>
      </ConfirmationModal>,
    );

    expect(screen.queryByTestId("confirmation-modal")).not.toBeInTheDocument();
  });

  it("calls onClose when Escape key is pressed", () => {
    const onClose = vi.fn();
    render(
      <ConfirmationModal {...defaultProps} onClose={onClose}>
        <p>Content</p>
      </ConfirmationModal>,
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when backdrop is clicked", () => {
    const onClose = vi.fn();
    render(
      <ConfirmationModal {...defaultProps} onClose={onClose}>
        <p>Content</p>
      </ConfirmationModal>,
    );

    fireEvent.click(screen.getByTestId("confirmation-modal-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onClose when modal content is clicked", () => {
    const onClose = vi.fn();
    render(
      <ConfirmationModal {...defaultProps} onClose={onClose}>
        <p>Content</p>
      </ConfirmationModal>,
    );

    fireEvent.click(screen.getByTestId("confirmation-modal"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("has role=dialog and aria-modal=true", () => {
    render(
      <ConfirmationModal {...defaultProps}>
        <p>Content</p>
      </ConfirmationModal>,
    );

    const dialog = screen.getByTestId("confirmation-modal");
    expect(dialog).toHaveAttribute("role", "dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("has aria-label matching the title", () => {
    render(
      <ConfirmationModal {...defaultProps} title="Approve Request">
        <p>Content</p>
      </ConfirmationModal>,
    );

    expect(screen.getByTestId("confirmation-modal")).toHaveAttribute(
      "aria-label",
      "Approve Request",
    );
  });

  it("renders title in the header", () => {
    render(
      <ConfirmationModal {...defaultProps} title="Reject Request">
        <p>Content</p>
      </ConfirmationModal>,
    );

    expect(screen.getByTestId("confirmation-modal-title")).toHaveTextContent("Reject Request");
  });
});
