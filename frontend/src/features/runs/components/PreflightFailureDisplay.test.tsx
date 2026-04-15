/**
 * Tests for PreflightFailureDisplay component.
 *
 * Verifies §8.3 requirements: structured rejection reasons with
 * blocker codes, owner cards, and next-step actions.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PreflightFailureDisplay } from "./PreflightFailureDisplay";
import type { PreflightResult } from "@/types/run";

function makeFailedPreflight(blockerCodes: string[] = ["PREFLIGHT_FAILED"]): PreflightResult[] {
  return [
    {
      passed: false,
      blockers: blockerCodes.map((code) => ({
        code,
        message: `Blocker for ${code}`,
        blocker_owner: "data-team@fxlab.io",
        next_step: "resolve",
        metadata: {},
      })),
      checked_at: "2026-04-04T10:00:00Z",
    },
  ];
}

describe("PreflightFailureDisplay", () => {
  it("renders nothing when all preflight results passed", () => {
    const { container } = render(
      <PreflightFailureDisplay
        preflightResults={[{ passed: true, blockers: [], checked_at: "2026-04-04T10:00:00Z" }]}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders blocker cards for failed preflight", () => {
    render(<PreflightFailureDisplay preflightResults={makeFailedPreflight()} />);
    expect(screen.getByTestId("preflight-failure-display")).toBeInTheDocument();
    expect(screen.getByTestId("blocker-card")).toBeInTheDocument();
  });

  it("shows blocker count in header", () => {
    render(
      <PreflightFailureDisplay
        preflightResults={makeFailedPreflight(["PREFLIGHT_FAILED", "MATERIAL_AMBIGUITY"])}
      />,
    );
    expect(screen.getByText(/2 blockers/)).toBeInTheDocument();
  });

  it("renders plain-language copy from BLOCKER_CODE_REGISTRY", () => {
    render(
      <PreflightFailureDisplay preflightResults={makeFailedPreflight(["PREFLIGHT_FAILED"])} />,
    );
    expect(screen.getByText("Pre-run validation did not pass.")).toBeInTheDocument();
  });

  it("shows blocker code as badge", () => {
    render(
      <PreflightFailureDisplay preflightResults={makeFailedPreflight(["DATASET_UNCERTIFIED"])} />,
    );
    expect(screen.getByText("DATASET_UNCERTIFIED")).toBeInTheDocument();
  });

  it("shows blocker owner", () => {
    render(<PreflightFailureDisplay preflightResults={makeFailedPreflight()} />);
    expect(screen.getByText("data-team@fxlab.io")).toBeInTheDocument();
  });

  it("shows next-step action button", () => {
    render(
      <PreflightFailureDisplay preflightResults={makeFailedPreflight(["PREFLIGHT_FAILED"])} />,
    );
    const nextStepBtn = screen.getByTestId("blocker-next-step");
    expect(nextStepBtn).toBeInTheDocument();
    expect(nextStepBtn.textContent).toContain("Review the preflight report");
  });

  it("uses singular 'blocker' for single blocker", () => {
    render(
      <PreflightFailureDisplay preflightResults={makeFailedPreflight(["PREFLIGHT_FAILED"])} />,
    );
    expect(screen.getByText(/1 blocker$/)).toBeInTheDocument();
  });
});
