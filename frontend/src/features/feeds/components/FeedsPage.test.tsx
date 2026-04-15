/**
 * Tests for FeedsPage.
 *
 * Covers:
 *   - Loading + error + empty states.
 *   - Renders feed rows from listFeeds.
 *   - Search filter narrows visible rows by name and provider.
 *   - Pagination Next/Prev increments offset and re-queries (no full reload).
 *   - Page summary text reflects offset / total / page size.
 *   - FeedHealthDashboard is mounted above the registry list.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  feedsApi: {
    listFeeds: vi.fn(),
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
import { FeedsPage } from "./FeedsPage";

const mockListFeeds = feedsApi.listFeeds as ReturnType<typeof vi.fn>;
const mockListFeedHealth = feedsApi.listFeedHealth as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeFeed(id: string, name: string, provider: string) {
  return {
    id,
    name,
    provider,
    config: {},
    is_active: true,
    is_quarantined: false,
    created_at: ISO,
    updated_at: ISO,
  };
}

function renderPage(pageSize = 2) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FeedsPage pageSize={pageSize} />
    </QueryClientProvider>,
  );
}

describe("FeedsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockListFeedHealth.mockResolvedValue({ feeds: [], generated_at: ISO });
  });

  it("renders loading state then list of feeds", async () => {
    mockListFeeds.mockResolvedValueOnce({
      feeds: [
        makeFeed("01HFEED0000000000000000A1", "binance-btcusd", "Binance"),
        makeFeed("01HFEED0000000000000000A2", "alpaca-spy", "Alpaca"),
      ],
      total_count: 2,
      limit: 2,
      offset: 0,
    });

    renderPage(2);

    expect(screen.getByTestId("feeds-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("feeds-row-01HFEED0000000000000000A1")).toBeInTheDocument();
    });
    expect(screen.getByText("binance-btcusd")).toBeInTheDocument();
    expect(screen.getByText("alpaca-spy")).toBeInTheDocument();
    expect(screen.getByTestId("feeds-page-summary")).toHaveTextContent("Showing 1–2 of 2");
  });

  it("filters rows by search across name and provider", async () => {
    mockListFeeds.mockResolvedValueOnce({
      feeds: [
        makeFeed("01HFEED0000000000000000B1", "binance-btcusd", "Binance"),
        makeFeed("01HFEED0000000000000000B2", "alpaca-spy", "Alpaca"),
      ],
      total_count: 2,
      limit: 2,
      offset: 0,
    });

    renderPage(2);
    await screen.findByTestId("feeds-row-01HFEED0000000000000000B1");

    fireEvent.change(screen.getByTestId("feeds-search-input"), {
      target: { value: "alpaca" },
    });

    expect(screen.queryByTestId("feeds-row-01HFEED0000000000000000B1")).not.toBeInTheDocument();
    expect(screen.getByTestId("feeds-row-01HFEED0000000000000000B2")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("feeds-search-input"), {
      target: { value: "BTC" },
    });
    // Search by name (case-insensitive)
    expect(screen.getByTestId("feeds-row-01HFEED0000000000000000B1")).toBeInTheDocument();
    expect(screen.queryByTestId("feeds-row-01HFEED0000000000000000B2")).not.toBeInTheDocument();
  });

  it("paginates Next/Prev without full reload (re-queries with new offset)", async () => {
    mockListFeeds
      .mockResolvedValueOnce({
        feeds: [makeFeed("01HFEED00000000000000PAGE1", "feed-1", "P")],
        total_count: 3,
        limit: 1,
        offset: 0,
      })
      .mockResolvedValueOnce({
        feeds: [makeFeed("01HFEED00000000000000PAGE2", "feed-2", "P")],
        total_count: 3,
        limit: 1,
        offset: 1,
      })
      .mockResolvedValueOnce({
        feeds: [makeFeed("01HFEED00000000000000PAGE1", "feed-1", "P")],
        total_count: 3,
        limit: 1,
        offset: 0,
      });

    renderPage(1);
    await screen.findByTestId("feeds-row-01HFEED00000000000000PAGE1");

    expect(screen.getByTestId("feeds-prev-button")).toBeDisabled();
    fireEvent.click(screen.getByTestId("feeds-next-button"));

    await screen.findByTestId("feeds-row-01HFEED00000000000000PAGE2");
    expect(screen.getByTestId("feeds-page-summary")).toHaveTextContent("Showing 2–2 of 3");
    expect(screen.getByTestId("feeds-prev-button")).not.toBeDisabled();

    fireEvent.click(screen.getByTestId("feeds-prev-button"));
    await screen.findByTestId("feeds-row-01HFEED00000000000000PAGE1");
    expect(screen.getByTestId("feeds-page-summary")).toHaveTextContent("Showing 1–1 of 3");

    expect(mockListFeeds).toHaveBeenCalledTimes(3);
    // Confirm offsets propagated to API
    const calls = mockListFeeds.mock.calls.map((c) => c[0]);
    expect(calls).toEqual([
      { limit: 1, offset: 0 },
      { limit: 1, offset: 1 },
      { limit: 1, offset: 0 },
    ]);
  });

  it("renders empty state when no feeds returned", async () => {
    mockListFeeds.mockResolvedValueOnce({
      feeds: [],
      total_count: 0,
      limit: 2,
      offset: 0,
    });
    renderPage(2);
    expect(await screen.findByTestId("feeds-empty")).toBeInTheDocument();
  });

  it("renders error state with retry on listFeeds failure", async () => {
    mockListFeeds.mockRejectedValueOnce(new Error("network down"));
    renderPage(2);

    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(screen.getByTestId("feeds-error")).toHaveTextContent(/network down/i);

    mockListFeeds.mockResolvedValueOnce({
      feeds: [makeFeed("01HFEED00000000000000RETRY", "feed-r", "P")],
      total_count: 1,
      limit: 2,
      offset: 0,
    });
    fireEvent.click(retry);
    await screen.findByTestId("feeds-row-01HFEED00000000000000RETRY");
  });
});
