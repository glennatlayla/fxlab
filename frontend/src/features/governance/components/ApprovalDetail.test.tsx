/**
 * Tests for ApprovalDetail component.
 *
 * Covers: status display, submitter metadata, SoD enforcement,
 * approve/reject modals with rationale validation, decided state.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ApprovalDetail } from "./ApprovalDetail";
import type { ApprovalDetail as ApprovalDetailType } from "@/types/governance";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeApproval(overrides?: Partial<ApprovalDetailType>): ApprovalDetailType {
  return {
    id: "01HAPPROVAL000000000001",
    requested_by: "01HUSER0000000000000001",
    status: "pending",
    created_at: "2026-04-06T12:00:00Z",
    ...overrides,
  };
}

const reviewer = "01HUSER0000000000000002";
const submitter = "01HUSER0000000000000001";

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe("ApprovalDetail", () => {
  it("renders status badge and submitter", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByTestId("approval-status-badge")).toHaveTextContent("Pending");
    expect(screen.getByTestId("approval-submitter")).toHaveTextContent(submitter);
  });

  it("renders approve and reject buttons for pending approvals when user is not submitter", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByTestId("approve-button")).toBeInTheDocument();
    expect(screen.getByTestId("reject-button")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // SoD enforcement (AC-2)
  // -------------------------------------------------------------------------

  it("renders SeparationGuard block when current user is the submitter", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={submitter}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByTestId("separation-guard-block")).toBeInTheDocument();
    expect(screen.queryByTestId("approve-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("reject-button")).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Approve flow
  // -------------------------------------------------------------------------

  it("opens approve confirmation modal on button click", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("approve-button"));
    expect(screen.getByTestId("confirmation-modal")).toBeInTheDocument();
    expect(screen.getByText("Approve Request")).toBeInTheDocument();
  });

  it("calls onApprove when confirm approve is clicked", () => {
    const onApprove = vi.fn();
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("approve-button"));
    fireEvent.click(screen.getByTestId("confirm-approve-button"));
    expect(onApprove).toHaveBeenCalledWith("01HAPPROVAL000000000001");
  });

  // -------------------------------------------------------------------------
  // Reject flow
  // -------------------------------------------------------------------------

  it("opens reject confirmation modal on button click", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("reject-button"));
    expect(screen.getByTestId("confirmation-modal")).toBeInTheDocument();
    expect(screen.getByText("Reject Request")).toBeInTheDocument();
  });

  it("disables confirm reject button when rationale is too short", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("reject-button"));
    expect(screen.getByTestId("confirm-reject-button")).toBeDisabled();

    fireEvent.change(screen.getByTestId("reject-rationale-input"), {
      target: { value: "too short" },
    });
    expect(screen.getByTestId("confirm-reject-button")).toBeDisabled();
  });

  it("enables confirm reject button when rationale meets minimum length", () => {
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("reject-button"));
    fireEvent.change(screen.getByTestId("reject-rationale-input"), {
      target: { value: "This evidence link is stale and no longer valid." },
    });
    expect(screen.getByTestId("confirm-reject-button")).not.toBeDisabled();
  });

  it("calls onReject with approval ID and rationale", () => {
    const onReject = vi.fn();
    render(
      <ApprovalDetail
        approval={makeApproval()}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={onReject}
      />,
    );

    fireEvent.click(screen.getByTestId("reject-button"));
    fireEvent.change(screen.getByTestId("reject-rationale-input"), {
      target: { value: "Evidence link is stale." },
    });
    fireEvent.click(screen.getByTestId("confirm-reject-button"));

    expect(onReject).toHaveBeenCalledWith("01HAPPROVAL000000000001", "Evidence link is stale.");
  });

  // -------------------------------------------------------------------------
  // Decided state
  // -------------------------------------------------------------------------

  it("hides action buttons for approved requests", () => {
    render(
      <ApprovalDetail
        approval={makeApproval({
          status: "approved",
          reviewer_id: reviewer,
          decided_at: "2026-04-06T14:00:00Z",
        })}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("approve-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("reject-button")).not.toBeInTheDocument();
    expect(screen.getByTestId("approval-status-badge")).toHaveTextContent("Approved");
  });

  it("displays decision reason for rejected requests", () => {
    render(
      <ApprovalDetail
        approval={makeApproval({
          status: "rejected",
          decision_reason: "Insufficient evidence for grade change.",
        })}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByTestId("approval-decision-reason")).toHaveTextContent(
      "Insufficient evidence for grade change.",
    );
  });

  it("renders reviewer when present", () => {
    render(
      <ApprovalDetail
        approval={makeApproval({
          status: "approved",
          reviewer_id: reviewer,
        })}
        currentUserId={reviewer}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByTestId("approval-reviewer")).toHaveTextContent(reviewer);
  });
});
