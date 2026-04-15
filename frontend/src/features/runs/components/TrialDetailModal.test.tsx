/**
 * Tests for TrialDetailModal component.
 *
 * Verifies modal rendering, trial data display, keyboard/backdrop close,
 * and handling of optional fields (seed, fold metrics, objective value).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TrialDetailModal } from "./TrialDetailModal";
import type { TrialRecord } from "@/types/run";

function makeTrial(overrides: Partial<TrialRecord> = {}): TrialRecord {
  return {
    id: "01HZ0000000000000000000010",
    run_id: "01HZ0000000000000000000001",
    trial_index: 5,
    status: "completed",
    parameters: { lookback: 20, threshold: 0.5 },
    seed: 42,
    metrics: { sharpe: 1.5, max_drawdown: -0.08 },
    created_at: "2026-04-04T10:02:00Z",
    updated_at: "2026-04-04T10:03:00Z",
    ...overrides,
  };
}

describe("TrialDetailModal", () => {
  it("renders nothing when isOpen is false", () => {
    render(<TrialDetailModal trial={makeTrial()} isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByTestId("trial-detail-modal")).not.toBeInTheDocument();
  });

  it("renders nothing when trial is null", () => {
    render(<TrialDetailModal trial={null} isOpen={true} onClose={vi.fn()} />);
    expect(screen.queryByTestId("trial-detail-modal")).not.toBeInTheDocument();
  });

  it("renders modal with trial index in header", () => {
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByTestId("trial-detail-modal")).toBeInTheDocument();
    expect(screen.getByText("Trial #5")).toBeInTheDocument();
  });

  it("displays trial parameters", () => {
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("lookback")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("threshold")).toBeInTheDocument();
    expect(screen.getByText("0.5")).toBeInTheDocument();
  });

  it("displays metrics", () => {
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("sharpe")).toBeInTheDocument();
    expect(screen.getByText("1.500000")).toBeInTheDocument();
  });

  it("displays seed when present", () => {
    render(<TrialDetailModal trial={makeTrial({ seed: 42 })} isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("displays objective value when present", () => {
    render(
      <TrialDetailModal
        trial={makeTrial({ objective_value: 1.234567 })}
        isOpen={true}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("1.234567")).toBeInTheDocument();
  });

  it("displays fold metrics when present", () => {
    render(
      <TrialDetailModal
        trial={makeTrial({
          fold_metrics: {
            fold_0: { sharpe: 1.2, drawdown: -0.05 },
          },
        })}
        isOpen={true}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("fold_0")).toBeInTheDocument();
    expect(screen.getByText("1.200000")).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("trial-modal-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on Escape key", () => {
    const onClose = vi.fn();
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on backdrop click", () => {
    const onClose = vi.fn();
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={onClose} />);
    const backdrop = screen.getByTestId("trial-detail-modal");
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("has accessible dialog role", () => {
    render(<TrialDetailModal trial={makeTrial()} isOpen={true} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });
});
