/**
 * ApprovalCardList — unit tests.
 *
 * Verifies that ApprovalCardList renders approval cards, supports
 * status filtering via chip controls, and handles loading/empty states.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalCardList } from "../ApprovalCardList";
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

describe("ApprovalCardList", () => {
  it("renders all approvals by default", () => {
    const approvals = [
      createMockApproval({ id: "a1", status: "pending" }),
      createMockApproval({ id: "a2", status: "approved" }),
      createMockApproval({ id: "a3", status: "rejected" }),
    ];
    const onApprovalClick = vi.fn();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    expect(screen.getByTestId("approval-card-list")).toBeInTheDocument();
    // All three cards should be rendered
    const cards = screen.getAllByTestId("approval-card");
    expect(cards).toHaveLength(3);
  });

  it("filters to pending approvals when pending chip is clicked", async () => {
    const approvals = [
      createMockApproval({ id: "a1", status: "pending", requested_by: "user1" }),
      createMockApproval({ id: "a2", status: "approved", requested_by: "user2" }),
    ];
    const onApprovalClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    // Click the "Pending" filter chip (must be specific to avoid ambiguity)
    const chips = screen.getAllByRole("button");
    const pendingChip = chips.find((chip) => chip.textContent?.includes("Pending"));
    if (!pendingChip) throw new Error("Pending chip not found");
    await user.click(pendingChip);

    // Only pending approval should be rendered
    const cards = screen.getAllByTestId("approval-card");
    expect(cards).toHaveLength(1);
    const submitter = screen.getByTestId("approval-card-submitter");
    expect(submitter).toHaveTextContent("user1");
  });

  it("filters to approved approvals when approved chip is clicked", async () => {
    const approvals = [
      createMockApproval({ id: "a1", status: "pending", requested_by: "user1" }),
      createMockApproval({ id: "a2", status: "approved", requested_by: "user2" }),
    ];
    const onApprovalClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    // Click the "Approved" filter chip
    const chips = screen.getAllByRole("button");
    const approvedChip = chips.find((chip) => chip.textContent?.includes("Approved"));
    if (!approvedChip) throw new Error("Approved chip not found");
    await user.click(approvedChip);

    // Only approved approval should be rendered
    const cards = screen.getAllByTestId("approval-card");
    expect(cards).toHaveLength(1);
    const submitter = screen.getByTestId("approval-card-submitter");
    expect(submitter).toHaveTextContent("user2");
  });

  it("filters to rejected approvals when rejected chip is clicked", async () => {
    const approvals = [
      createMockApproval({ id: "a1", status: "pending", requested_by: "user1" }),
      createMockApproval({ id: "a2", status: "rejected", requested_by: "user3" }),
    ];
    const onApprovalClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    // Click the "Rejected" filter chip
    const chips = screen.getAllByRole("button");
    const rejectedChip = chips.find((chip) => chip.textContent?.includes("Rejected"));
    if (!rejectedChip) throw new Error("Rejected chip not found");
    await user.click(rejectedChip);

    // Only rejected approval should be rendered
    const cards = screen.getAllByTestId("approval-card");
    expect(cards).toHaveLength(1);
    const submitter = screen.getByTestId("approval-card-submitter");
    expect(submitter).toHaveTextContent("user3");
  });

  it("shows all approvals again when All chip is clicked", async () => {
    const approvals = [
      createMockApproval({ id: "a1", status: "pending" }),
      createMockApproval({ id: "a2", status: "approved" }),
    ];
    const onApprovalClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    // First filter to pending
    const chips = screen.getAllByRole("button");
    const pendingChip = chips.find((chip) => chip.textContent?.includes("Pending"));
    if (!pendingChip) throw new Error("Pending chip not found");
    await user.click(pendingChip);

    // Verify only one card is shown
    let cards = screen.getAllByTestId("approval-card");
    expect(cards).toHaveLength(1);

    // Then click "All"
    const allChip = chips.find((chip) => chip.textContent?.includes("All Statuses"));
    if (!allChip) throw new Error("All chip not found");
    await user.click(allChip);

    // Both should be rendered now
    cards = screen.getAllByTestId("approval-card");
    expect(cards).toHaveLength(2);
  });

  it("shows empty state when no approvals match filter", async () => {
    const approvals = [
      createMockApproval({ id: "a1", status: "pending" }),
    ];
    const onApprovalClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    // Filter to approved (but only pending exists)
    const approvedChip = screen.getByRole("button", { name: /approved/i });
    await user.click(approvedChip);

    // Empty state should appear
    expect(screen.getByTestId("approval-card-list-empty")).toBeInTheDocument();
  });

  it("shows loading skeleton when isLoading is true", () => {
    const onApprovalClick = vi.fn();

    render(
      <ApprovalCardList
        approvals={[]}
        onApprovalClick={onApprovalClick}
        isLoading={true}
      />,
    );

    expect(screen.getByTestId("approval-card-list-loading")).toBeInTheDocument();
  });

  it("calls onApprovalClick when a card is clicked", async () => {
    const approvals = [
      createMockApproval({ id: "approval-xyz" }),
    ];
    const onApprovalClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApprovalCardList approvals={approvals} onApprovalClick={onApprovalClick} />,
    );

    const card = screen.getByTestId("approval-card");
    await user.click(card);

    expect(onApprovalClick).toHaveBeenCalledWith("approval-xyz");
  });

  it("renders filter chips with correct labels", () => {
    const onApprovalClick = vi.fn();

    render(
      <ApprovalCardList approvals={[]} onApprovalClick={onApprovalClick} />,
    );

    const chips = screen.getAllByRole("button");
    const chipTexts = chips.map((c) => c.textContent);
    expect(chipTexts.join(" ")).toContain("All");
    expect(chipTexts.join(" ")).toContain("Pending");
    expect(chipTexts.join(" ")).toContain("Approved");
    expect(chipTexts.join(" ")).toContain("Rejected");
  });
});
