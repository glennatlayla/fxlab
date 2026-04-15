/**
 * Tests for ParityPage.
 *
 * Covers:
 *   - Loading + error + empty states.
 *   - Renders parity events table with severity badges, instrument, delta values, feed IDs.
 *   - Severity badges: CRITICAL badge uses red (not neutral).
 *   - Severity filter: filtering by status hides/shows events correctly.
 *   - Summary section: renders per-instrument summary with event counts and worst severity.
 *   - Page lifecycle logging (mount/unmount).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  parityApi: {
    listEvents: vi.fn(),
    getSummary: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  parityLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { parityApi } from "../api";
import { parityLogger } from "../logger";
import { ParityPage } from "./ParityPage";

const mockListEvents = parityApi.listEvents as ReturnType<typeof vi.fn>;
const mockGetSummary = parityApi.getSummary as ReturnType<typeof vi.fn>;
const mockPageMount = parityLogger.pageMount as ReturnType<typeof vi.fn>;
const mockPageUnmount = parityLogger.pageUnmount as ReturnType<typeof vi.fn>;

const ISO = "2026-04-10T12:00:00.000Z";

function makeEvent(
  id: string,
  instrument: string,
  severity: "INFO" | "WARNING" | "CRITICAL",
  delta: number,
) {
  return {
    id,
    feed_id_official: "feed-official-001",
    feed_id_shadow: "feed-shadow-001",
    instrument,
    timestamp: ISO,
    delta,
    delta_pct: (delta / 100) * 100,
    severity,
    detected_at: ISO,
  };
}

function makeSummary(
  instrument: string,
  event_count: number,
  critical_count: number,
  warning_count: number,
  info_count: number,
  worst_severity: string,
) {
  return {
    instrument,
    event_count,
    critical_count,
    warning_count,
    info_count,
    worst_severity,
  };
}

function renderPage(pageSize = 20) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ParityPage pageSize={pageSize} />
    </QueryClientProvider>,
  );
}

describe("ParityPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state then list of parity events", async () => {
    mockListEvents.mockResolvedValueOnce({
      events: [
        makeEvent("event-001", "EURUSD", "INFO", 0.001),
        makeEvent("event-002", "GBPUSD", "WARNING", 0.005),
      ],
      total_count: 2,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [
        makeSummary("EURUSD", 1, 0, 0, 1, "INFO"),
        makeSummary("GBPUSD", 1, 0, 1, 0, "WARNING"),
      ],
      total_event_count: 2,
      generated_at: ISO,
    });

    renderPage(20);

    expect(screen.getByTestId("parity-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("parity-events-table")).toBeInTheDocument();
    });
    expect(screen.getByTestId("parity-event-row-event-001")).toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-002")).toBeInTheDocument();
  });

  it("renders error state with retry on listEvents failure", async () => {
    mockListEvents.mockRejectedValueOnce(new Error("network error"));
    mockGetSummary.mockResolvedValueOnce({
      summaries: [],
      total_event_count: 0,
      generated_at: ISO,
    });

    renderPage(20);

    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(screen.getByTestId("parity-error")).toHaveTextContent(/network error/i);

    mockListEvents.mockResolvedValueOnce({
      events: [makeEvent("event-retry", "EURUSD", "CRITICAL", 0.05)],
      total_count: 1,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [makeSummary("EURUSD", 1, 1, 0, 0, "CRITICAL")],
      total_event_count: 1,
      generated_at: ISO,
    });
    fireEvent.click(retry);
    await screen.findByTestId("parity-events-table");
  });

  it("renders empty state when no events", async () => {
    mockListEvents.mockResolvedValueOnce({
      events: [],
      total_count: 0,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [],
      total_event_count: 0,
      generated_at: ISO,
    });

    renderPage(20);
    expect(await screen.findByTestId("parity-empty")).toBeInTheDocument();
  });

  it("renders parity events table with all columns and severity badge", async () => {
    mockListEvents.mockResolvedValueOnce({
      events: [
        makeEvent("event-001", "EURUSD", "INFO", 0.001),
        makeEvent("event-002", "GBPUSD", "CRITICAL", 0.05),
      ],
      total_count: 2,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [
        makeSummary("EURUSD", 1, 0, 0, 1, "INFO"),
        makeSummary("GBPUSD", 1, 1, 0, 0, "CRITICAL"),
      ],
      total_event_count: 2,
      generated_at: ISO,
    });

    renderPage(20);
    await screen.findByTestId("parity-events-table");

    // Check event rows exist
    expect(screen.getByTestId("parity-event-row-event-001")).toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-002")).toBeInTheDocument();

    // Check feed IDs (multiple instances OK)
    expect(screen.getAllByText("feed-official-001")).toHaveLength(2);
    expect(screen.getAllByText("feed-shadow-001")).toHaveLength(2);

    // Check delta values
    expect(screen.getByText("0.001")).toBeInTheDocument();
    expect(screen.getByText("0.05")).toBeInTheDocument();
  });

  it("CRITICAL severity badge uses red color class (not neutral)", async () => {
    mockListEvents.mockResolvedValueOnce({
      events: [makeEvent("event-001", "EURUSD", "CRITICAL", 0.05)],
      total_count: 1,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [makeSummary("EURUSD", 1, 1, 0, 0, "CRITICAL")],
      total_event_count: 1,
      generated_at: ISO,
    });

    renderPage(20);
    await screen.findByTestId("parity-events-table");

    // Get the severity badge within the table row
    const eventRow = screen.getByTestId("parity-event-row-event-001");
    const criticalBadge = eventRow.querySelector("span");

    expect(criticalBadge).toBeTruthy();
    expect(criticalBadge).toHaveClass("bg-red-100");
    expect(criticalBadge).toHaveClass("text-red-800");

    // Assert badge class matches red pattern and NOT neutral (slate/zinc/gray)
    const badgeClass = criticalBadge!.className;
    expect(badgeClass).toMatch(/red/);
    expect(badgeClass).not.toMatch(/(slate|zinc|gray)-/);
  });

  it("filters events by severity status (All, INFO, WARNING, CRITICAL)", async () => {
    const events = [
      makeEvent("event-001", "EURUSD", "INFO", 0.001),
      makeEvent("event-002", "GBPUSD", "WARNING", 0.005),
      makeEvent("event-003", "AUDUSD", "CRITICAL", 0.05),
    ];
    mockListEvents.mockResolvedValueOnce({
      events,
      total_count: 3,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [
        makeSummary("EURUSD", 1, 0, 0, 1, "INFO"),
        makeSummary("GBPUSD", 1, 0, 1, 0, "WARNING"),
        makeSummary("AUDUSD", 1, 1, 0, 0, "CRITICAL"),
      ],
      total_event_count: 3,
      generated_at: ISO,
    });

    renderPage(20);
    await screen.findByTestId("parity-events-table");

    // All events visible initially
    expect(screen.getByTestId("parity-event-row-event-001")).toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-002")).toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-003")).toBeInTheDocument();

    // Filter to CRITICAL only
    const severityFilter = screen.getByTestId("parity-severity-filter");
    fireEvent.change(severityFilter, { target: { value: "CRITICAL" } });

    // Only CRITICAL visible
    expect(screen.queryByTestId("parity-event-row-event-001")).not.toBeInTheDocument();
    expect(screen.queryByTestId("parity-event-row-event-002")).not.toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-003")).toBeInTheDocument();

    // Filter to WARNING
    fireEvent.change(severityFilter, { target: { value: "WARNING" } });
    expect(screen.queryByTestId("parity-event-row-event-001")).not.toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-002")).toBeInTheDocument();
    expect(screen.queryByTestId("parity-event-row-event-003")).not.toBeInTheDocument();

    // Filter back to All
    fireEvent.change(severityFilter, { target: { value: "All" } });
    expect(screen.getByTestId("parity-event-row-event-001")).toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-002")).toBeInTheDocument();
    expect(screen.getByTestId("parity-event-row-event-003")).toBeInTheDocument();
  });

  it("renders summary section with per-instrument cards", async () => {
    mockListEvents.mockResolvedValueOnce({
      events: [
        makeEvent("event-001", "EURUSD", "INFO", 0.001),
        makeEvent("event-002", "GBPUSD", "CRITICAL", 0.05),
      ],
      total_count: 2,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [
        makeSummary("EURUSD", 2, 0, 1, 1, "WARNING"),
        makeSummary("GBPUSD", 1, 1, 0, 0, "CRITICAL"),
      ],
      total_event_count: 3,
      generated_at: ISO,
    });

    renderPage(20);
    await screen.findByTestId("parity-summary-section");

    expect(screen.getByTestId("parity-summary-eurusd")).toBeInTheDocument();
    expect(screen.getByTestId("parity-summary-gbpusd")).toBeInTheDocument();

    // Check event counts
    const eurusdCards = screen.getByTestId("parity-summary-eurusd");
    expect(eurusdCards).toHaveTextContent("2");
  });

  it("calls page lifecycle logging on mount and unmount", async () => {
    mockListEvents.mockResolvedValueOnce({
      events: [],
      total_count: 0,
      generated_at: ISO,
    });
    mockGetSummary.mockResolvedValueOnce({
      summaries: [],
      total_event_count: 0,
      generated_at: ISO,
    });

    const { unmount } = renderPage(20);

    await screen.findByTestId("parity-empty");
    expect(mockPageMount).toHaveBeenCalledWith("ParityPage", expect.any(String));

    unmount();
    expect(mockPageUnmount).toHaveBeenCalledWith("ParityPage", expect.any(String));
  });
});
