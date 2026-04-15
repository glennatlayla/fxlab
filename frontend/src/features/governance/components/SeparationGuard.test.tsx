/**
 * Tests for SeparationGuard component.
 *
 * AC-2: Submitter cannot approve their own request — SeparationGuard
 * renders a blocking notice and hides action buttons.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SeparationGuard } from "./SeparationGuard";

describe("SeparationGuard", () => {
  const submitter = "01HUSER0000000000000001";
  const reviewer = "01HUSER0000000000000002";

  it("renders children when current user is not the submitter", () => {
    render(
      <SeparationGuard currentUserId={reviewer} submitterId={submitter}>
        <button>Approve</button>
        <button>Reject</button>
      </SeparationGuard>,
    );

    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.queryByTestId("separation-guard-block")).not.toBeInTheDocument();
  });

  it("renders SoD block and hides children when current user is the submitter", () => {
    render(
      <SeparationGuard currentUserId={submitter} submitterId={submitter}>
        <button>Approve</button>
        <button>Reject</button>
      </SeparationGuard>,
    );

    expect(screen.getByTestId("separation-guard-block")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("displays separation of duties message", () => {
    render(
      <SeparationGuard currentUserId={submitter} submitterId={submitter}>
        <button>Approve</button>
      </SeparationGuard>,
    );

    expect(screen.getByText("Separation of Duties")).toBeInTheDocument();
    expect(screen.getByText(/cannot review your own request/i)).toBeInTheDocument();
  });

  it("has role=status on the guard block for accessibility", () => {
    render(
      <SeparationGuard currentUserId={submitter} submitterId={submitter}>
        <button>Approve</button>
      </SeparationGuard>,
    );

    expect(screen.getByTestId("separation-guard-block")).toHaveAttribute("role", "status");
  });
});
