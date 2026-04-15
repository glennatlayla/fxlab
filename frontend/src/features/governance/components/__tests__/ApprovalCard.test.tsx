/**
 * ApprovalCard — unit tests.
 *
 * Verifies that ApprovalCard renders correctly and handles user interactions
 * as specified in the component interface.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalCard } from "../ApprovalCard";
import type { ApprovalDetail } from "@/types/governance";

/**
 * Factory for creating mock ApprovalDetail instances.
 */
function createMockApproval(overrides?: Partial<ApprovalDetail>): ApprovalDetail {
  return {
    id: "approval-1",
    candidate_id: "cand-123",
    entity_type: "candidate",
    entity_id: "cand-123",
    requested_by: "alice@example.com",
    reviewer_id: null,
    status: "pending",
    decision_reason: null,
    decided_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("ApprovalCard", () => {
  it("renders status badge with pending state (amber)", () => {
    const approval = createMockApproval({ status: "pending" });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const badge = screen.getByTestId("approval-card-status-badge");
    expect(badge).toHaveTextContent("Pending");
    expect(badge).toHaveClass("bg-yellow-100");
  });

  it("renders status badge with approved state (green)", () => {
    const approval = createMockApproval({ status: "approved" });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const badge = screen.getByTestId("approval-card-status-badge");
    expect(badge).toHaveTextContent("Approved");
    expect(badge).toHaveClass("bg-emerald-100");
  });

  it("renders status badge with rejected state (red)", () => {
    const approval = createMockApproval({ status: "rejected" });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const badge = screen.getByTestId("approval-card-status-badge");
    expect(badge).toHaveTextContent("Rejected");
    expect(badge).toHaveClass("bg-red-100");
  });

  it("renders submitter name", () => {
    const approval = createMockApproval({ requested_by: "bob@example.com" });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    expect(screen.getByTestId("approval-card-submitter")).toHaveTextContent("bob@example.com");
  });

  it("renders formatted timestamp", () => {
    const timestamp = "2026-04-13T10:30:00Z";
    const approval = createMockApproval({ created_at: timestamp });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const timestampEl = screen.getByTestId("approval-card-timestamp");
    expect(timestampEl).toBeInTheDocument();
    // Just verify it contains a date representation (exact format depends on locale)
    expect(timestampEl.textContent).toBeTruthy();
  });

  it("renders entity type and ID when available", () => {
    const approval = createMockApproval({
      entity_type: "candidate",
      entity_id: "cand-123",
    });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const entityEl = screen.getByTestId("approval-card-entity");
    expect(entityEl).toHaveTextContent("candidate");
    expect(entityEl).toHaveTextContent("cand-123");
  });

  it("renders decision reason when available", () => {
    const approval = createMockApproval({
      decision_reason: "Did not meet requirements",
    });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const reasonEl = screen.getByTestId("approval-card-decision-reason");
    expect(reasonEl).toHaveTextContent("Did not meet requirements");
  });

  it("does not render decision reason when absent", () => {
    const approval = createMockApproval({ decision_reason: null });
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    expect(screen.queryByTestId("approval-card-decision-reason")).not.toBeInTheDocument();
  });

  it("calls onClick with approval ID when card is clicked", async () => {
    const approval = createMockApproval({ id: "approval-xyz" });
    const onClick = vi.fn();
    const user = userEvent.setup();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const card = screen.getByTestId("approval-card");
    await user.click(card);

    expect(onClick).toHaveBeenCalledWith("approval-xyz");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders chevron icon to indicate tappable element", () => {
    const approval = createMockApproval();
    const onClick = vi.fn();

    render(<ApprovalCard approval={approval} onClick={onClick} />);

    const chevron = screen.getByTestId("approval-card-chevron");
    expect(chevron).toBeInTheDocument();
  });
});
