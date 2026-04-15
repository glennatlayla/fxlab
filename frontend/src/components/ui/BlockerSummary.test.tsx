/**
 * Tests for BlockerSummary component.
 *
 * Acceptance criteria (M22):
 *   - Renders owner display name and next-step button for a known code.
 *   - Renders raw code + fallback text for an unknown code.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { BlockerSummary } from "./BlockerSummary";

function renderBlocker(props: Partial<React.ComponentProps<typeof BlockerSummary>> = {}) {
  const defaults = {
    blockerCode: "PENDING_APPROVAL",
    ownerDisplayName: "Jane Doe",
    nextStepLabel: "Request Approval",
    onNextStep: vi.fn(),
    ...props,
  };
  return render(
    <MemoryRouter>
      <BlockerSummary {...defaults} />
    </MemoryRouter>,
  );
}

describe("BlockerSummary", () => {
  it("renders owner display name for known blocker code", () => {
    renderBlocker();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
  });

  it("renders next-step button for known blocker code", () => {
    renderBlocker();
    expect(screen.getByRole("button", { name: "Request Approval" })).toBeInTheDocument();
  });

  it("renders description for known blocker code", () => {
    renderBlocker({ blockerCode: "PENDING_APPROVAL" });
    expect(
      screen.getByText("Waiting for governance approval before promotion."),
    ).toBeInTheDocument();
  });

  it("renders fallback text for unknown blocker code", () => {
    renderBlocker({ blockerCode: "MYSTERY_CODE" });
    expect(screen.getByText(/Unknown Blocker/)).toBeInTheDocument();
    expect(screen.getByText(/MYSTERY_CODE/)).toBeInTheDocument();
  });

  it("calls onNextStep when button is clicked", async () => {
    const onNextStep = vi.fn();
    renderBlocker({ onNextStep });
    await userEvent.click(screen.getByRole("button", { name: "Request Approval" }));
    expect(onNextStep).toHaveBeenCalledTimes(1);
  });
});
