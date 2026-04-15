/**
 * Tests for FeedHealthDashboard.
 *
 * Covers:
 *   - Loading state.
 *   - Error state with retry button.
 *   - Summary counts per status.
 *   - Degraded badge cannot be suppressed (renders with non-neutral classes).
 *   - Attention list shows degraded + quarantined entries.
 *   - Empty (all-healthy) state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  feedsApi: {
    listFeedHealth: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  feedsLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { feedsApi } from "../api";
import { FeedHealthDashboard } from "./FeedHealthDashboard";

const mockListFeedHealth = feedsApi.listFeedHealth as ReturnType<typeof vi.fn>;

function makeReport(status: "healthy" | "degraded" | "quarantined" | "offline", feedId: string) {
  return {
    feed_id: feedId,
    status,
    last_update: "2026-04-06T12:00:00.000Z",
    recent_anomalies: [],
    quarantine_reason: status === "quarantined" ? "Stale data" : null,
  };
}

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FeedHealthDashboard />
    </QueryClientProvider>,
  );
}

describe("FeedHealthDashboard", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state while fetching", () => {
    mockListFeedHealth.mockReturnValue(new Promise(() => {}));
    renderDashboard();
    expect(screen.getByTestId("feed-health-loading")).toBeInTheDocument();
  });

  it("renders error state with retry", async () => {
    mockListFeedHealth.mockRejectedValueOnce(new Error("boom"));
    renderDashboard();
    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(screen.getByTestId("feed-health-error")).toHaveTextContent(/boom/i);
    mockListFeedHealth.mockResolvedValueOnce({
      feeds: [makeReport("healthy", "01HFEED0000000000000000001")],
      generated_at: "2026-04-06T12:00:00.000Z",
    });
    fireEvent.click(retry);
    await screen.findByTestId("feed-health-dashboard");
  });

  it("summarizes counts and surfaces degraded + quarantined feeds", async () => {
    mockListFeedHealth.mockResolvedValueOnce({
      feeds: [
        makeReport("healthy", "01HFEED0000000000000000001"),
        makeReport("healthy", "01HFEED0000000000000000002"),
        makeReport("degraded", "01HFEED0000000000000000003"),
        makeReport("quarantined", "01HFEED0000000000000000004"),
        makeReport("offline", "01HFEED0000000000000000005"),
      ],
      generated_at: "2026-04-06T12:00:00.000Z",
    });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("feed-health-summary-healthy")).toHaveTextContent("2");
    });
    expect(screen.getByTestId("feed-health-summary-degraded")).toHaveTextContent("1");
    expect(screen.getByTestId("feed-health-summary-quarantined")).toHaveTextContent("1");
    expect(screen.getByTestId("feed-health-summary-offline")).toHaveTextContent("1");

    // Degraded + quarantined surfaced; offline / healthy NOT in attention list.
    expect(screen.getByTestId("feed-health-row-01HFEED0000000000000000003")).toBeInTheDocument();
    expect(screen.getByTestId("feed-health-row-01HFEED0000000000000000004")).toBeInTheDocument();
    expect(
      screen.queryByTestId("feed-health-row-01HFEED0000000000000000001"),
    ).not.toBeInTheDocument();
  });

  it("renders degraded badge with non-neutral colour (cannot be suppressed)", async () => {
    mockListFeedHealth.mockResolvedValueOnce({
      feeds: [makeReport("degraded", "01HFEED0000000000000000010")],
      generated_at: "2026-04-06T12:00:00.000Z",
    });
    renderDashboard();

    const badge = await screen.findByTestId("feed-health-badge-01HFEED0000000000000000010");
    expect(badge).toHaveTextContent("Degraded");
    // Non-neutral: amber palette per FEED_HEALTH_BADGE_CLASSES.
    expect(badge.className).toMatch(/amber/);
    // Must NOT use neutral slate/zinc/gray palette.
    expect(badge.className).not.toMatch(/(slate|zinc|gray)-/);
  });

  it("shows all-healthy empty message when no attention feeds", async () => {
    mockListFeedHealth.mockResolvedValueOnce({
      feeds: [makeReport("healthy", "01HFEED0000000000000000020")],
      generated_at: "2026-04-06T12:00:00.000Z",
    });
    renderDashboard();
    expect(await screen.findByTestId("feed-health-empty")).toHaveTextContent(
      /all feeds are healthy/i,
    );
  });
});
