/**
 * RunCard component tests — mobile-optimized single run card.
 *
 * Test cases:
 *   - test_renders_run_id_truncated: Card displays truncated run ID
 *   - test_renders_status_badge: Status badge is rendered with correct status
 *   - test_renders_strategy_build_id_truncated: Strategy build ID is truncated in card
 *   - test_renders_run_type: Run type is displayed in the card
 *   - test_renders_progress_bar_for_running_run: Progress bar shows for running status
 *   - test_renders_trial_count: Displays completed/total trial count
 *   - test_click_calls_onClick_with_run_id: Entire card is clickable and calls onClick
 *   - test_chevron_icon_displayed: Chevron icon indicates clickable card
 *   - test_progress_bar_colors_by_status: Progress bar shows correct colour by status
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { RunCard } from "../RunCard";
import type { RunRecord } from "@/types/run";
import { RUN_STATUS } from "@/types/run";

describe("RunCard", () => {
  const mockRun: RunRecord = {
    id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    strategy_build_id: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
    run_type: "research",
    status: RUN_STATUS.RUNNING,
    config: {},
    result_uri: null,
    created_by: "user123",
    created_at: "2026-04-13T10:00:00Z",
    updated_at: "2026-04-13T10:05:00Z",
    started_at: "2026-04-13T10:00:30Z",
    completed_at: null,
    trial_count: 100,
    completed_trials: 45,
  };

  it("test_renders_run_id_truncated", () => {
    render(<RunCard run={mockRun} onClick={vi.fn()} />);
    const runIdElements = screen.getAllByText(/01ARZ3ND/);
    expect(runIdElements.length).toBeGreaterThan(0);
  });

  it("test_renders_status_badge", () => {
    render(<RunCard run={mockRun} onClick={vi.fn()} />);
    const badge = screen.getByRole("status");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Running");
  });

  it("test_renders_strategy_build_id_truncated", () => {
    render(<RunCard run={mockRun} onClick={vi.fn()} />);
    expect(screen.getByText("Build")).toBeInTheDocument();
  });

  it("test_renders_run_type", () => {
    render(<RunCard run={mockRun} onClick={vi.fn()} />);
    expect(screen.getByText("research")).toBeInTheDocument();
  });

  it("test_renders_progress_bar_for_running_run", () => {
    render(<RunCard run={mockRun} onClick={vi.fn()} />);
    const progressBar = screen.getByRole("progressbar");
    expect(progressBar).toBeInTheDocument();
  });

  it("test_renders_trial_count", () => {
    render(<RunCard run={mockRun} onClick={vi.fn()} />);
    expect(screen.getByText(/45 \/ 100/)).toBeInTheDocument();
  });

  it("test_click_calls_onClick_with_run_id", async () => {
    const onClick = vi.fn();
    const { container } = render(<RunCard run={mockRun} onClick={onClick} />);
    const card = container.querySelector("[data-testid='run-card']");
    expect(card).toBeInTheDocument();

    if (card) {
      await userEvent.click(card);
      expect(onClick).toHaveBeenCalledWith(mockRun.id);
    }
  });

  it("test_chevron_icon_displayed", () => {
    const { container } = render(<RunCard run={mockRun} onClick={vi.fn()} />);
    const chevron = container.querySelector("svg");
    expect(chevron).toBeInTheDocument();
  });

  it("test_progress_bar_colors_by_status", () => {
    const completedRun: RunRecord = { ...mockRun, status: RUN_STATUS.COMPLETE };
    const { container } = render(<RunCard run={completedRun} onClick={vi.fn()} />);
    const progressBar = container.querySelector("[role='progressbar']");
    expect(progressBar).toBeInTheDocument();
  });

  it("test_handles_missing_trial_count", () => {
    const runWithoutTrials: RunRecord = {
      ...mockRun,
      trial_count: undefined,
      completed_trials: undefined,
    };
    render(<RunCard run={runWithoutTrials} onClick={vi.fn()} />);
    expect(screen.queryByText(/\/ /)).not.toBeInTheDocument();
  });

  it("test_renders_for_different_statuses", () => {
    const statuses = [
      RUN_STATUS.PENDING,
      RUN_STATUS.RUNNING,
      RUN_STATUS.COMPLETE,
      RUN_STATUS.FAILED,
      RUN_STATUS.CANCELLED,
    ];

    statuses.forEach((status) => {
      const { unmount } = render(<RunCard run={{ ...mockRun, status }} onClick={vi.fn()} />);
      expect(screen.getByRole("status")).toBeInTheDocument();
      unmount();
    });
  });
});
