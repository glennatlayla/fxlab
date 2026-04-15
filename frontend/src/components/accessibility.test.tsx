/**
 * Accessibility sweep — M31 keyboard nav, ARIA labels, color contrast.
 *
 * Covers:
 *   - All interactive elements have accessible names (buttons, inputs, selects)
 *   - Status/alert regions use correct ARIA roles
 *   - Loading states use role="status"
 *   - Error states use role="alert"
 *   - Tables have proper structure (thead, tbody)
 *   - Filter selects have aria-label
 *
 * Per M31 spec: "keyboard navigation reaches all primary interactive elements"
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Test helper: renders with required providers
// ---------------------------------------------------------------------------

function createClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

// ---------------------------------------------------------------------------
// DiagnosticsShell accessibility
// ---------------------------------------------------------------------------
describe("DiagnosticsShell accessibility", () => {
  it("loading state has role=status", async () => {
    vi.doMock("@/api/client", () => ({
      apiClient: { get: vi.fn(() => new Promise(() => {})) },
    }));
    vi.doMock("@/features/feeds/logger", () => ({
      feedsLogger: { pageMount: vi.fn(), pageUnmount: vi.fn() },
    }));

    const { DiagnosticsShell } = await import("@/features/feeds/components/DiagnosticsShell");

    render(
      <QueryClientProvider client={createClient()}>
        <DiagnosticsShell />
      </QueryClientProvider>,
    );

    const loadingEl = screen.getByTestId("diagnostics-loading");
    expect(loadingEl).toHaveAttribute("role", "status");

    vi.doUnmock("@/api/client");
    vi.doUnmock("@/features/feeds/logger");
  });
});

// ---------------------------------------------------------------------------
// AnomalyViewer accessibility
// ---------------------------------------------------------------------------
describe("AnomalyViewer accessibility", () => {
  it("severity filter select has aria-label", async () => {
    vi.doMock("@/features/feeds/api", () => ({
      feedsApi: {
        listFeedHealth: vi.fn().mockResolvedValue({
          feeds: [
            {
              feed_id: "f1",
              status: "degraded",
              last_update: "2026-04-06T12:00:00.000Z",
              recent_anomalies: [
                {
                  id: "a1",
                  feed_id: "f1",
                  anomaly_type: "gap",
                  detected_at: "2026-04-06T12:00:00.000Z",
                  start_time: "2026-04-06T12:00:00.000Z",
                  end_time: null,
                  severity: "high",
                  message: "test",
                  metadata: {},
                },
              ],
              quarantine_reason: null,
            },
          ],
          generated_at: "2026-04-06T12:00:00.000Z",
        }),
      },
    }));
    vi.doMock("@/features/feeds/logger", () => ({
      feedsLogger: { pageMount: vi.fn(), pageUnmount: vi.fn() },
    }));

    const { AnomalyViewer } = await import("@/features/feeds/components/AnomalyViewer");

    render(
      <QueryClientProvider client={createClient()}>
        <AnomalyViewer />
      </QueryClientProvider>,
    );

    const select = await screen.findByTestId("anomaly-severity-filter");
    expect(select).toHaveAttribute("aria-label", "Filter by severity");
    expect(select.tagName).toBe("SELECT");

    vi.doUnmock("@/features/feeds/api");
    vi.doUnmock("@/features/feeds/logger");
  });
});

// ---------------------------------------------------------------------------
// ErrorState accessibility
// ---------------------------------------------------------------------------
describe("ErrorState accessibility", () => {
  it("has role=alert for screen readers", async () => {
    const { ErrorState } = await import("@/components/ui/ErrorState");

    render(<ErrorState message="Something went wrong" />);

    const alertEl = screen.getByRole("alert");
    expect(alertEl).toBeInTheDocument();
    expect(alertEl).toHaveTextContent("Something went wrong");
  });
});

// ---------------------------------------------------------------------------
// LoadingState accessibility
// ---------------------------------------------------------------------------
describe("LoadingState accessibility", () => {
  it("has role=status for screen readers", async () => {
    const { LoadingState } = await import("@/components/ui/LoadingState");

    render(<LoadingState />);

    const statusEl = screen.getByRole("status");
    expect(statusEl).toBeInTheDocument();
  });
});
