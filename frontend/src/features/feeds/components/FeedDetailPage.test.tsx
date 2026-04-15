/**
 * Tests for FeedDetailPage.
 *
 * Covers:
 *   - Loading state.
 *   - 404 → not-found state (no Retry button).
 *   - Generic error → error state with Retry.
 *   - Happy path renders metadata, version history, connectivity tests.
 *   - Cross-fetched health report surfaces status badge + recent anomalies.
 *   - Empty subsections render their empty messages.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  feedsApi: {
    getFeed: vi.fn(),
    listFeedHealth: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  feedsLogger: { pageMount: vi.fn(), pageUnmount: vi.fn() },
}));

import { feedsApi } from "../api";
import { FeedsNotFoundError } from "../errors";
import { FeedDetailPage } from "./FeedDetailPage";

const mockGetFeed = feedsApi.getFeed as ReturnType<typeof vi.fn>;
const mockListFeedHealth = feedsApi.listFeedHealth as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";
const FEED_ID = "01HFEED0000000000000000F1";

function makeDetail(overrides: Record<string, unknown> = {}) {
  return {
    feed: {
      id: FEED_ID,
      name: "binance-btcusd",
      provider: "Binance",
      config: { symbol: "BTC/USD" },
      is_active: true,
      is_quarantined: false,
      created_at: ISO,
      updated_at: ISO,
    },
    version_history: [
      {
        version: 2,
        config: { symbol: "BTC/USD", interval: "1m" },
        created_at: ISO,
        created_by: "01HUSER0000000000000000000",
        change_summary: "interval 5m → 1m",
      },
      {
        version: 1,
        config: { symbol: "BTC/USD", interval: "5m" },
        created_at: ISO,
        created_by: "01HUSER0000000000000000000",
        change_summary: null,
      },
    ],
    connectivity_tests: [
      {
        id: "01HCONN000000000000000C1",
        feed_id: FEED_ID,
        tested_at: ISO,
        status: "ok",
        latency_ms: 42,
        error_message: null,
      },
    ],
    ...overrides,
  };
}

function makeHealth(status: "healthy" | "degraded" = "degraded", anomalies = true) {
  return {
    feeds: [
      {
        feed_id: FEED_ID,
        status,
        last_update: ISO,
        recent_anomalies: anomalies
          ? [
              {
                id: "01HANOM00000000000000A1",
                feed_id: FEED_ID,
                anomaly_type: "gap",
                detected_at: ISO,
                start_time: ISO,
                end_time: null,
                severity: "high",
                message: "5m gap detected",
                metadata: {},
              },
            ]
          : [],
        quarantine_reason: null,
      },
    ],
    generated_at: ISO,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FeedDetailPage feedId={FEED_ID} />
    </QueryClientProvider>,
  );
}

describe("FeedDetailPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state while fetching", () => {
    mockGetFeed.mockReturnValue(new Promise(() => {}));
    mockListFeedHealth.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("feed-detail-loading")).toBeInTheDocument();
  });

  it("renders not-found state without Retry on 404", async () => {
    mockGetFeed.mockRejectedValueOnce(new FeedsNotFoundError(FEED_ID));
    mockListFeedHealth.mockResolvedValue(makeHealth("healthy", false));
    renderPage();
    await screen.findByTestId("feed-detail-not-found");
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("renders generic error state with Retry on non-404 failure", async () => {
    mockGetFeed.mockRejectedValueOnce(new Error("boom"));
    mockListFeedHealth.mockResolvedValue(makeHealth("healthy", false));
    renderPage();
    await screen.findByTestId("feed-detail-error");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders metadata, version history, connectivity tests, and degraded badge + anomalies from health report", async () => {
    mockGetFeed.mockResolvedValueOnce(makeDetail());
    mockListFeedHealth.mockResolvedValueOnce(makeHealth("degraded", true));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("feed-detail-page")).toBeInTheDocument();
    });
    expect(screen.getByText("binance-btcusd")).toBeInTheDocument();
    expect(screen.getByTestId("feed-detail-id")).toHaveTextContent(FEED_ID);

    // Version history
    expect(screen.getByTestId("feed-detail-version-2")).toHaveTextContent("v2");
    expect(screen.getByTestId("feed-detail-version-1")).toHaveTextContent("v1");
    expect(screen.getByText(/interval 5m → 1m/)).toBeInTheDocument();

    // Connectivity test
    expect(
      screen.getByTestId("feed-detail-connectivity-01HCONN000000000000000C1"),
    ).toHaveTextContent("OK");
    expect(screen.getByText("42 ms")).toBeInTheDocument();

    // Health badge from cross-fetched health report
    const badge = await screen.findByTestId(`feed-detail-health-badge-${FEED_ID}`);
    expect(badge).toHaveTextContent("Degraded");
    expect(badge.className).toMatch(/amber/);
    expect(badge.className).not.toMatch(/(slate|zinc|gray)-/);

    // Anomalies surfaced
    expect(screen.getByTestId("feed-detail-anomaly-01HANOM00000000000000A1")).toHaveTextContent(
      "Gap",
    );
    expect(screen.getByText("5m gap detected")).toBeInTheDocument();
  });

  it("renders empty subsections when detail has no versions/connectivity and health has no anomalies", async () => {
    mockGetFeed.mockResolvedValueOnce(makeDetail({ version_history: [], connectivity_tests: [] }));
    mockListFeedHealth.mockResolvedValueOnce(makeHealth("healthy", false));

    renderPage();

    await screen.findByTestId("feed-detail-page");
    expect(screen.getByTestId("feed-detail-versions-empty")).toBeInTheDocument();
    expect(screen.getByTestId("feed-detail-connectivity-empty")).toBeInTheDocument();
    expect(screen.getByTestId("feed-detail-anomalies-empty")).toBeInTheDocument();
  });
});
