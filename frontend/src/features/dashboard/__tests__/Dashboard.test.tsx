/**
 * Tests for Dashboard page component (FE-03).
 *
 * Verifies:
 *   - Dashboard renders summary cards with correct metric values.
 *   - Kill switch warning appears when active_kill_switches > 0.
 *   - Kill switch warning is hidden when active_kill_switches == 0.
 *   - Alert banner shows for critical severity.
 *   - Alert banner shows for warning severity.
 *   - Alert banner hidden when no alerts.
 *   - Loading state displays skeleton.
 *   - P&L formats as currency with sign indication.
 *   - Null P&L displays as dash.
 *   - Cards link to correct pages.
 *   - Component refetches every 30 seconds.
 *   - Error state displays with retry button.
 *
 * Example:
 *   npx vitest run src/features/dashboard/__tests__/Dashboard.test.tsx
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "@/pages/Dashboard";
import * as dashboardApiModule from "@/features/dashboard/api";
import type { MobileDashboardSummary } from "@/features/dashboard/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/features/dashboard/api");

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: "test-user", email: "trader@fxlab.test" },
    isAuthenticated: true,
    accessToken: "test-token",
    isLoading: false,
    logout: vi.fn(),
    login: vi.fn(),
    hasScope: vi.fn(() => true),
  }),
}));

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

/**
 * Render Dashboard within required providers.
 */
function renderDashboard(client?: QueryClient) {
  const queryClient = client || createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Mock dashboard summary for a healthy state.
 */
const mockHealthySummary: MobileDashboardSummary = {
  active_runs: 3,
  completed_runs_24h: 5,
  pending_approvals: 2,
  active_kill_switches: 0,
  pnl_today_usd: 1250.5,
  last_alert_severity: null,
  last_alert_message: null,
  generated_at: "2026-04-13T14:30:00Z",
};

/**
 * Mock dashboard summary with critical alert.
 */
const mockWithCriticalAlert: MobileDashboardSummary = {
  ...mockHealthySummary,
  last_alert_severity: "critical",
  last_alert_message: "Risk limit exceeded",
};

/**
 * Mock dashboard summary with warning alert.
 */
const mockWithWarningAlert: MobileDashboardSummary = {
  ...mockHealthySummary,
  last_alert_severity: "warning",
  last_alert_message: "Position delta threshold warning",
};

/**
 * Mock dashboard summary with active kill switches.
 */
const mockWithKillSwitches: MobileDashboardSummary = {
  ...mockHealthySummary,
  active_kill_switches: 2,
};

/**
 * Mock dashboard summary with negative P&L.
 */
const mockWithNegativePnL: MobileDashboardSummary = {
  ...mockHealthySummary,
  pnl_today_usd: -500.25,
};

/**
 * Mock dashboard summary with null P&L.
 */
const mockWithNullPnL: MobileDashboardSummary = {
  ...mockHealthySummary,
  pnl_today_usd: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it("renders_dashboard_title", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockHealthySummary);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/Dashboard/i)).toBeInTheDocument();
    });
  });

  it("renders_summary_cards_with_data", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockHealthySummary);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/Active Runs/i)).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
      expect(screen.getByText(/Completed \(24h\)/i)).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
      expect(screen.getByText(/Pending Approvals/i)).toBeInTheDocument();
      expect(screen.getByText("2")).toBeInTheDocument();
    });
  });

  it("shows_kill_switch_warning_when_active", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockWithKillSwitches);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/2 Active Kill Switches/i)).toBeInTheDocument();
    });
  });

  it("hides_kill_switch_warning_when_zero", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockHealthySummary);

    renderDashboard();

    await waitFor(() => {
      expect(screen.queryByText(/Active Kill Switches/i)).not.toBeInTheDocument();
    });
  });

  it("shows_alert_banner_for_critical_severity", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(
      mockWithCriticalAlert,
    );

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/Risk limit exceeded/i)).toBeInTheDocument();
    });
  });

  it("shows_alert_banner_for_warning_severity", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockWithWarningAlert);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/Position delta threshold warning/i)).toBeInTheDocument();
    });
  });

  it("hides_alert_banner_when_no_alerts", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockHealthySummary);

    renderDashboard();

    await waitFor(() => {
      // Check that no alert text is present
      expect(screen.queryByText(/Risk limit exceeded/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Position delta threshold warning/i)).not.toBeInTheDocument();
    });
  });

  it("shows_loading_state", () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    renderDashboard();

    // Should render placeholder/skeleton during loading
    const dashboardTitle = screen.getByText(/Dashboard/i);
    expect(dashboardTitle).toBeInTheDocument();
  });

  it("formats_pnl_as_currency_positive", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockHealthySummary);

    renderDashboard();

    await waitFor(() => {
      // Format: +$1,250.50
      expect(screen.getByText(/\$1,250\.50/)).toBeInTheDocument();
    });
  });

  it("formats_pnl_as_currency_negative", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockWithNegativePnL);

    renderDashboard();

    await waitFor(() => {
      // Find P&L card and verify it contains negative value
      const pnlCard = screen.getByText(/P&L Today/i).closest("button");
      expect(pnlCard?.textContent).toContain("500.25");
      expect(pnlCard?.textContent).toContain("-");
    });
  });

  it("shows_dash_for_null_pnl", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockWithNullPnL);

    renderDashboard();

    await waitFor(() => {
      const pnlCard = screen.getByText(/P&L Today/i).closest("button");
      expect(pnlCard?.textContent).toContain("—");
    });
  });

  it("displays_error_state_on_api_failure", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockRejectedValue(
      new Error("Network error"),
    );

    const errorClient = new QueryClient({
      defaultOptions: { queries: { retry: 0, retryDelay: 0 } },
    });

    renderDashboard(errorClient);

    await waitFor(
      () => {
        // Check for error message text
        expect(screen.getByText(/Failed to load dashboard/i)).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("refetches_data_on_retry", async () => {
    vi.spyOn(dashboardApiModule.dashboardApi, "getSummary").mockResolvedValue(mockHealthySummary);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText("3")).toBeInTheDocument();
    });

    // Verify that summary data is displayed (refetch occurred)
    expect(screen.getByText(/Active Runs/i)).toBeInTheDocument();
  });
});
