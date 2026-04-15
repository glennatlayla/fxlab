/**
 * Tests for OverrideRequestForm component.
 *
 * AC-3: Form rejects submission when evidence_link is empty.
 * AC-4: Form rejects submission when evidence_link is not a valid URL.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OverrideRequestForm } from "./OverrideRequestForm";

describe("OverrideRequestForm", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onSubmit: vi.fn(),
  };

  it("renders form when open", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    expect(screen.getByText("Request Governance Override")).toBeInTheDocument();
    expect(screen.getByTestId("override-object-id-input")).toBeInTheDocument();
    expect(screen.getByTestId("override-evidence-link-input")).toBeInTheDocument();
    expect(screen.getByTestId("override-rationale-input")).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(<OverrideRequestForm {...defaultProps} isOpen={false} />);

    expect(screen.queryByText("Request Governance Override")).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // AC-3: evidence_link empty rejection
  // -------------------------------------------------------------------------

  it("shows error when evidence_link is empty on submit", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    // Fill minimum fields but leave evidence_link empty.
    fireEvent.change(screen.getByTestId("override-object-id-input"), {
      target: { value: "01HCANDIDATE0000000001" },
    });
    fireEvent.change(screen.getByTestId("override-rationale-input"), {
      target: {
        value: "Extended backtest over 3-year window justifies grade uplift.",
      },
    });

    fireEvent.click(screen.getByTestId("override-form-submit"));

    expect(screen.getByTestId("evidence-link-error")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // AC-4: evidence_link invalid URL rejection
  // -------------------------------------------------------------------------

  it("shows error when evidence_link is not a valid URL on submit", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    fireEvent.change(screen.getByTestId("override-object-id-input"), {
      target: { value: "01HCANDIDATE0000000001" },
    });
    fireEvent.change(screen.getByTestId("override-evidence-link-input"), {
      target: { value: "not-a-url" },
    });
    fireEvent.change(screen.getByTestId("override-rationale-input"), {
      target: {
        value: "Extended backtest over 3-year window justifies grade uplift.",
      },
    });

    fireEvent.click(screen.getByTestId("override-form-submit"));

    expect(screen.getByTestId("evidence-link-error")).toBeInTheDocument();
  });

  it("shows error when evidence_link is root-only URL on submit", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    fireEvent.change(screen.getByTestId("override-object-id-input"), {
      target: { value: "01HCANDIDATE0000000001" },
    });
    fireEvent.change(screen.getByTestId("override-evidence-link-input"), {
      target: { value: "https://jira.example.com/" },
    });
    fireEvent.change(screen.getByTestId("override-rationale-input"), {
      target: {
        value: "Extended backtest over 3-year window justifies grade uplift.",
      },
    });

    fireEvent.click(screen.getByTestId("override-form-submit"));

    expect(screen.getByTestId("evidence-link-error")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Rationale validation
  // -------------------------------------------------------------------------

  it("shows error when rationale is too short on submit", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    fireEvent.change(screen.getByTestId("override-object-id-input"), {
      target: { value: "01HCANDIDATE0000000001" },
    });
    fireEvent.change(screen.getByTestId("override-evidence-link-input"), {
      target: { value: "https://jira.example.com/browse/FX-123" },
    });
    fireEvent.change(screen.getByTestId("override-rationale-input"), {
      target: { value: "too short" },
    });

    fireEvent.click(screen.getByTestId("override-form-submit"));

    expect(screen.getByTestId("rationale-error")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Success path
  // -------------------------------------------------------------------------

  it("calls onSubmit with valid form data", () => {
    const onSubmit = vi.fn();
    render(<OverrideRequestForm {...defaultProps} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByTestId("override-object-id-input"), {
      target: { value: "01HCANDIDATE0000000001" },
    });
    fireEvent.change(screen.getByTestId("override-evidence-link-input"), {
      target: { value: "https://jira.example.com/browse/FX-123" },
    });
    fireEvent.change(screen.getByTestId("override-rationale-input"), {
      target: {
        value: "Extended backtest over 3-year window justifies grade uplift.",
      },
    });

    fireEvent.click(screen.getByTestId("override-form-submit"));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        object_id: "01HCANDIDATE0000000001",
        evidence_link: "https://jira.example.com/browse/FX-123",
        rationale: "Extended backtest over 3-year window justifies grade uplift.",
        object_type: "candidate",
        override_type: "grade_override",
      }),
    );
  });

  // -------------------------------------------------------------------------
  // Inline help
  // -------------------------------------------------------------------------

  it("displays evidence link inline help text", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    expect(
      screen.getByText(/Paste a link to your Jira ticket, Confluence doc, or GitHub issue/i),
    ).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Cancel
  // -------------------------------------------------------------------------

  it("calls onClose when cancel is clicked", () => {
    const onClose = vi.fn();
    render(<OverrideRequestForm {...defaultProps} onClose={onClose} />);

    fireEvent.click(screen.getByTestId("override-form-cancel"));
    expect(onClose).toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Character count
  // -------------------------------------------------------------------------

  it("shows rationale character count", () => {
    render(<OverrideRequestForm {...defaultProps} />);

    expect(screen.getByText("0/20 characters minimum")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("override-rationale-input"), {
      target: { value: "twelve chars" },
    });
    expect(screen.getByText("12/20 characters minimum")).toBeInTheDocument();
  });
});
