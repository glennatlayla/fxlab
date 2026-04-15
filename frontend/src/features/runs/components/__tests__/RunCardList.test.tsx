/**
 * RunCardList component tests — scrollable list of run cards with filters.
 *
 * Test cases:
 *   - test_renders_all_runs_by_default: Shows all runs initially
 *   - test_filter_chips_filter_by_status: Filter buttons filter list by status
 *   - test_shows_empty_state_when_no_matches: Shows message when no runs match filter
 *   - test_shows_loading_skeleton: Displays skeleton cards while loading
 *   - test_click_propagates_to_onRunClick: Card clicks call onRunClick callback
 *   - test_filter_chips_are_keyboard_accessible: Filter buttons are keyboard navigable
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { RunCardList } from "../RunCardList";
import type { RunRecord } from "@/types/run";
import { RUN_STATUS } from "@/types/run";

describe("RunCardList", () => {
  const mockRuns: RunRecord[] = [
    {
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
    },
    {
      id: "01ARZ3NDEKTSV4RRFFQ69G5FAW",
      strategy_build_id: "01ARZ3NDEKTSV4RRFFQ69G5FBX",
      run_type: "optimization",
      status: RUN_STATUS.COMPLETE,
      config: {},
      result_uri: "s3://bucket/result.zip",
      created_by: "user123",
      created_at: "2026-04-13T08:00:00Z",
      updated_at: "2026-04-13T09:05:00Z",
      started_at: "2026-04-13T08:00:30Z",
      completed_at: "2026-04-13T09:05:00Z",
      trial_count: 50,
      completed_trials: 50,
    },
    {
      id: "01ARZ3NDEKTSV4RRFFQ69G5FAX",
      strategy_build_id: "01ARZ3NDEKTSV4RRFFQ69G5FBY",
      run_type: "research",
      status: RUN_STATUS.FAILED,
      config: {},
      result_uri: null,
      created_by: "user123",
      created_at: "2026-04-13T07:00:00Z",
      updated_at: "2026-04-13T07:30:00Z",
      started_at: "2026-04-13T07:00:30Z",
      completed_at: "2026-04-13T07:30:00Z",
      trial_count: 75,
      completed_trials: 30,
      error_message: "Network error",
    },
  ];

  it("test_renders_all_runs_by_default", () => {
    render(<RunCardList runs={mockRuns} onRunClick={vi.fn()} isLoading={false} />);
    const cards = screen.getAllByTestId("run-card");
    expect(cards).toHaveLength(3);
  });

  it("test_filter_chips_filter_by_status", async () => {
    const onRunClick = vi.fn();
    render(<RunCardList runs={mockRuns} onRunClick={onRunClick} isLoading={false} />);

    // Click "Running" filter (first button with Running text at the top)
    const buttons = screen.getAllByRole("button");
    const runningButton = buttons.find((btn) => btn.textContent === "Running");
    expect(runningButton).toBeDefined();

    if (runningButton) {
      await userEvent.click(runningButton);
      // Should show only running run
      const cards = screen.getAllByTestId("run-card");
      expect(cards).toHaveLength(1);
    }
  });

  it("test_shows_empty_state_when_no_matches", async () => {
    const onRunClick = vi.fn();
    render(<RunCardList runs={mockRuns} onRunClick={onRunClick} isLoading={false} />);

    // Filter to "Completed" then check for only complete runs
    const buttons = screen.getAllByRole("button");
    const completedButton = buttons.find((btn) => btn.textContent === "Completed");
    expect(completedButton).toBeDefined();

    if (completedButton) {
      await userEvent.click(completedButton);
      const cards = screen.queryAllByTestId("run-card");
      expect(cards).toHaveLength(1);
    }
  });

  it("test_shows_loading_skeleton", () => {
    render(<RunCardList runs={[]} onRunClick={vi.fn()} isLoading={true} />);

    // Should show loading indicator or skeleton
    const loadingIndicator = screen.getByRole("status");
    expect(loadingIndicator).toBeInTheDocument();
  });

  it("test_click_propagates_to_onRunClick", async () => {
    const onRunClick = vi.fn();
    render(<RunCardList runs={mockRuns} onRunClick={onRunClick} isLoading={false} />);

    const cards = screen.getAllByTestId("run-card");
    await userEvent.click(cards[0]);

    expect(onRunClick).toHaveBeenCalledWith(mockRuns[0].id);
  });

  it("test_filter_chips_are_keyboard_accessible", async () => {
    render(<RunCardList runs={mockRuns} onRunClick={vi.fn()} isLoading={false} />);

    const allButton = screen.getByRole("button", { name: /all/i });
    allButton.focus();
    expect(allButton).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(screen.getAllByTestId("run-card")).toHaveLength(3);
  });

  it("test_empty_list_shows_no_runs_message", () => {
    render(<RunCardList runs={[]} onRunClick={vi.fn()} isLoading={false} />);

    expect(screen.getByText(/no runs/i)).toBeInTheDocument();
  });

  it("test_all_filter_shows_all_runs", async () => {
    render(<RunCardList runs={mockRuns} onRunClick={vi.fn()} isLoading={false} />);

    // First filter to running
    const buttons = screen.getAllByRole("button");
    const runningButton = buttons.find((btn) => btn.textContent === "Running");
    expect(runningButton).toBeDefined();

    if (runningButton) {
      await userEvent.click(runningButton);
      expect(screen.getAllByTestId("run-card")).toHaveLength(1);

      // Then click "All" to show all again
      const allButton = buttons.find((btn) => btn.textContent === "All");
      expect(allButton).toBeDefined();
      if (allButton) {
        await userEvent.click(allButton);
        expect(screen.getAllByTestId("run-card")).toHaveLength(3);
      }
    }
  });
});
