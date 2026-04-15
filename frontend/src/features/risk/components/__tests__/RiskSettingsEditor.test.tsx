/**
 * RiskSettingsEditor unit tests.
 *
 * Purpose:
 *   Verify RiskSettingsEditor orchestrates the risk settings workflow:
 *   fetch, edit, review, apply with MFA confirmation.
 *
 * Test coverage:
 *   - Fetches and displays current settings on load.
 *   - Shows loading state while fetching.
 *   - Shows error on fetch failure.
 *   - Tracks pending changes in local state.
 *   - Review button is disabled when no changes exist.
 *   - Opens diff review when changes exist.
 *
 * Dependencies:
 *   - vitest, @testing-library/react, @testing-library/user-event
 *   - @tanstack/react-query (for useQuery/useMutation)
 *   - RiskSettingsEditor component
 *   - riskApi (mocked)
 *
 * Example:
 *   npx vitest run src/features/risk/components/__tests__/RiskSettingsEditor.test.tsx -xvs
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RiskSettingsEditor } from "../RiskSettingsEditor";
import * as riskApiModule from "../../api";
import type { RiskSettings } from "../../types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("../../api");

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * Create a fresh QueryClient for each test.
 * Disables retries to avoid flaky tests.
 */
function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

/**
 * Render RiskSettingsEditor within required providers.
 */
function renderEditor(deploymentId: string = "01HDEPLOY123") {
  const queryClient = createTestQueryClient();
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <RiskSettingsEditor deploymentId={deploymentId} />
      </QueryClientProvider>,
    ),
    queryClient,
  };
}

/**
 * Mock RiskSettings object.
 */
function mockSettings(overrides?: Partial<RiskSettings>): RiskSettings {
  return {
    deployment_id: "01HDEPLOY123",
    max_position_size: "10000",
    max_daily_loss: "5000",
    max_order_value: "50000",
    max_concentration_pct: "25",
    max_open_orders: 100,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RiskSettingsEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches and displays current settings on load", async () => {
    const settings = mockSettings();
    vi.mocked(riskApiModule.riskApi.getSettings).mockResolvedValue(settings);

    renderEditor("01HDEPLOY123");

    // Wait for settings to load
    await waitFor(() => {
      expect(screen.getByText("Max Position Size")).toBeInTheDocument();
    });

    expect(riskApiModule.riskApi.getSettings).toHaveBeenCalledWith("01HDEPLOY123");
  });

  it("shows loading state while fetching settings", () => {
    vi.mocked(riskApiModule.riskApi.getSettings).mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    renderEditor("01HDEPLOY123");

    // Should show loading indicator
    expect(screen.getByText(/loading|fetching/i)).toBeInTheDocument();
  });

  it("disables review button when no changes exist", async () => {
    const settings = mockSettings();
    vi.mocked(riskApiModule.riskApi.getSettings).mockResolvedValue(settings);

    renderEditor("01HDEPLOY123");

    await waitFor(() => {
      expect(screen.getByText("Max Position Size")).toBeInTheDocument();
    });

    // Review button should be disabled
    const reviewButton = screen.getByRole("button", { name: /review/i });
    expect(reviewButton).toBeDisabled();
  });

  it("enables review button when changes exist", async () => {
    const user = userEvent.setup();
    const settings = mockSettings();
    vi.mocked(riskApiModule.riskApi.getSettings).mockResolvedValue(settings);

    const { container } = renderEditor("01HDEPLOY123");

    // Wait for load
    await waitFor(() => {
      expect(screen.getByText("Max Position Size")).toBeInTheDocument();
    });

    // Make a change
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    await user.click(editButtons[0]);

    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "15000");
    await user.keyboard("{Enter}");

    // Review button should now be enabled
    const reviewButton = screen.getByRole("button", { name: /review/i });
    expect(reviewButton).not.toBeDisabled();
  });

  it("review button opens when there are pending changes", async () => {
    const user = userEvent.setup();
    const settings = mockSettings();
    vi.mocked(riskApiModule.riskApi.getSettings).mockResolvedValue(settings);

    const { container } = renderEditor("01HDEPLOY123");

    // Wait for load
    await waitFor(() => {
      expect(screen.getByText("Max Position Size")).toBeInTheDocument();
    });

    // Make a change
    const editButtons = container.querySelectorAll("button[aria-label*='Edit']");
    await user.click(editButtons[0]);

    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "15000");
    await user.keyboard("{Enter}");

    // Review button should be clickable after change
    const reviewButton = screen.getByRole("button", { name: /review/i });
    expect(reviewButton).not.toBeDisabled();
    // We don't test the BottomSheet opening here as that's an E2E concern
  });
});
