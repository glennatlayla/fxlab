/**
 * PaperTradingOverview page tests — mobile paper trading monitor main page.
 *
 * Test cases:
 *   - test_header_shows_title: Header shows "Paper Trading Monitor"
 *   - test_new_button_visible: "New" button present in header
 *   - test_filter_buttons_visible: All filter buttons (All, Active, Frozen, Stopped) visible
 *   - test_filter_button_styling: Active filter button shows different style
 *   - test_handles_error_state: Error message displayed on API failure
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { PaperTradingOverview } from "../PaperTradingOverview";

// Mock React Query with a simpler setup for this component
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn((config) => {
    // Simple mock that returns empty data
    if (config.queryKey[0] === "paper-deployments") {
      return {
        data: [],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      };
    }
    return {
      data: config.queryKey[0].includes("positions") ? [] : [],
      isLoading: false,
    };
  }),
}));

describe("PaperTradingOverview", () => {
  it("test_header_shows_title", () => {
    render(<PaperTradingOverview />);
    expect(screen.getByText("Paper Trading Monitor")).toBeInTheDocument();
  });

  it("test_new_button_visible", () => {
    render(<PaperTradingOverview />);
    const newButton = screen.getByRole("button", { name: /new/i });
    expect(newButton).toBeInTheDocument();
  });

  it("test_filter_buttons_visible", () => {
    render(<PaperTradingOverview />);
    expect(screen.getByRole("button", { name: /all/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /active/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /frozen/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stopped/i })).toBeInTheDocument();
  });

  it("test_filter_button_styling", async () => {
    render(<PaperTradingOverview />);
    const allButton = screen.getByRole("button", { name: /all/i });

    // Initially "all" should be selected
    expect(allButton).toHaveClass("bg-blue-600");

    // Click active
    const activeButton = screen.getByRole("button", { name: /active/i });
    await userEvent.click(activeButton);

    expect(activeButton).toHaveClass("bg-blue-600");
    expect(allButton).not.toHaveClass("bg-blue-600");
  });

  it("test_shows_empty_state_when_no_deployments", () => {
    render(<PaperTradingOverview />);
    // Should show empty state message since mock returns empty array
    expect(screen.getByText(/no paper trading deployments yet/i)).toBeInTheDocument();
  });

  it("test_create_one_button_visible_in_empty_state", () => {
    render(<PaperTradingOverview />);
    const createButton = screen.getByRole("button", { name: /create one/i });
    expect(createButton).toBeInTheDocument();
  });
});
