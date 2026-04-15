/**
 * Tests for AnomalyViewer.
 *
 * Covers:
 *   - Loading state while health report is being fetched.
 *   - Error state with Retry button on fetch failure.
 *   - Happy path: renders anomalies from multiple feeds in a unified table.
 *   - Severity filter: selecting "high" hides "low" anomalies.
 *   - Empty state when no anomalies exist across all feeds.
 *   - Anomaly type labels use human-readable form (Gap, Spike, etc.).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  feedsApi: {
    listFeedHealth: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  feedsLogger: { pageMount: vi.fn(), pageUnmount: vi.fn() },
}));

import { feedsApi } from "../api";
import { AnomalyViewer } from "./AnomalyViewer";

const mockListFeedHealth = feedsApi.listFeedHealth as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";
const FEED_A = "01HFEED0000000000000000F1";
const FEED_B = "01HFEED0000000000000000F2";

function makeHealthReport(feeds: Array<Record<string, unknown>> = []) {
  return {
    feeds,
    generated_at: ISO,
  };
}

function makeFeedHealth(feedId: string, anomalies: Array<Record<string, unknown>> = []) {
  return {
    feed_id: feedId,
    status: "degraded",
    last_update: ISO,
    recent_anomalies: anomalies,
    quarantine_reason: null,
  };
}

function makeAnomaly(id: string, feedId: string, type: string, severity: string, message: string) {
  return {
    id,
    feed_id: feedId,
    anomaly_type: type,
    detected_at: ISO,
    start_time: ISO,
    end_time: null,
    severity,
    message,
    metadata: {},
  };
}

function renderViewer() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AnomalyViewer />
    </QueryClientProvider>,
  );
}

describe("AnomalyViewer", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state while fetching health report", () => {
    mockListFeedHealth.mockReturnValue(new Promise(() => {}));
    renderViewer();
    expect(screen.getByTestId("anomaly-viewer-loading")).toBeInTheDocument();
  });

  it("renders error state with Retry on fetch failure", async () => {
    mockListFeedHealth.mockRejectedValueOnce(new Error("network down"));
    renderViewer();
    await screen.findByTestId("anomaly-viewer-error");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders anomalies from multiple feeds in a unified table", async () => {
    mockListFeedHealth.mockResolvedValueOnce(
      makeHealthReport([
        makeFeedHealth(FEED_A, [makeAnomaly("01HA1", FEED_A, "gap", "high", "5m gap detected")]),
        makeFeedHealth(FEED_B, [
          makeAnomaly("01HA2", FEED_B, "spike", "low", "price spike"),
          makeAnomaly("01HA3", FEED_B, "stale", "medium", "stale data"),
        ]),
      ]),
    );

    renderViewer();
    await screen.findByTestId("anomaly-viewer-table");

    // Three anomaly rows
    expect(screen.getByTestId("anomaly-row-01HA1")).toBeInTheDocument();
    expect(screen.getByTestId("anomaly-row-01HA2")).toBeInTheDocument();
    expect(screen.getByTestId("anomaly-row-01HA3")).toBeInTheDocument();

    // Human-readable type labels
    expect(within(screen.getByTestId("anomaly-row-01HA1")).getByText("Gap")).toBeInTheDocument();
    expect(within(screen.getByTestId("anomaly-row-01HA2")).getByText("Spike")).toBeInTheDocument();
    expect(within(screen.getByTestId("anomaly-row-01HA3")).getByText("Stale")).toBeInTheDocument();

    // Messages
    expect(screen.getByText("5m gap detected")).toBeInTheDocument();
    expect(screen.getByText("price spike")).toBeInTheDocument();
    expect(screen.getByText("stale data")).toBeInTheDocument();

    // Feed IDs are surfaced
    expect(screen.getByTestId("anomaly-row-01HA1")).toHaveTextContent(FEED_A);
    expect(screen.getByTestId("anomaly-row-01HA2")).toHaveTextContent(FEED_B);
  });

  it("filters anomalies by severity", async () => {
    mockListFeedHealth.mockResolvedValueOnce(
      makeHealthReport([
        makeFeedHealth(FEED_A, [
          makeAnomaly("01HA1", FEED_A, "gap", "high", "5m gap detected"),
          makeAnomaly("01HA4", FEED_A, "duplicate", "low", "duplicate candle"),
        ]),
      ]),
    );

    renderViewer();
    await screen.findByTestId("anomaly-viewer-table");

    // Both visible initially
    expect(screen.getByTestId("anomaly-row-01HA1")).toBeInTheDocument();
    expect(screen.getByTestId("anomaly-row-01HA4")).toBeInTheDocument();

    // Select "high" severity filter
    const user = userEvent.setup();
    const filter = screen.getByTestId("anomaly-severity-filter");
    await user.selectOptions(filter, "high");

    // Only high-severity anomaly visible
    expect(screen.getByTestId("anomaly-row-01HA1")).toBeInTheDocument();
    expect(screen.queryByTestId("anomaly-row-01HA4")).not.toBeInTheDocument();
  });

  it("renders empty state when no anomalies exist", async () => {
    mockListFeedHealth.mockResolvedValueOnce(
      makeHealthReport([makeFeedHealth(FEED_A, []), makeFeedHealth(FEED_B, [])]),
    );

    renderViewer();
    await screen.findByTestId("anomaly-viewer-empty");
    expect(screen.getByTestId("anomaly-viewer-empty")).toHaveTextContent(/no anomalies/i);
  });
});
