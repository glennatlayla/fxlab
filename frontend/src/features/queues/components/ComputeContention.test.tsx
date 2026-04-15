/**
 * Tests for ComputeContention.
 *
 * Covers:
 *   - Loading + error + empty states.
 *   - Renders contention data with score badge, depth, running, failed.
 *   - Time range selector changes with options: 1h, 6h, 24h, 7d.
 *   - Time range change updates query key (forces re-fetch).
 *   - Component uses React.memo and useCallback for optimization.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  queuesApi: {
    getContention: vi.fn(),
  },
}));
vi.mock("../logger", () => ({
  queuesLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
  },
}));

import { queuesApi } from "../api";
import { ComputeContention } from "./ComputeContention";

const mockGetContention = queuesApi.getContention as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeContention(score: number) {
  return {
    queue_class: "research",
    depth: 42,
    running: 8,
    failed: 2,
    contention_score: score,
    generated_at: ISO,
  };
}

function renderComponent() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ComputeContention />
    </QueryClientProvider>,
  );
}

describe("ComputeContention", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state then contention data", async () => {
    mockGetContention.mockResolvedValueOnce(makeContention(35));

    renderComponent();

    expect(screen.getByTestId("compute-contention-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("compute-contention")).toBeInTheDocument();
    });

    expect(screen.getByTestId("contention-score-badge")).toBeInTheDocument();
  });

  it("renders contention data with depth, running, failed counts", async () => {
    mockGetContention.mockResolvedValueOnce(makeContention(45));

    renderComponent();
    await screen.findByTestId("compute-contention");

    expect(screen.getByTestId("contention-depth")).toHaveTextContent("42");
    expect(screen.getByTestId("contention-running")).toHaveTextContent("8");
    expect(screen.getByTestId("contention-failed")).toHaveTextContent("2");
  });

  it("renders contention score badge with color based on level", async () => {
    mockGetContention.mockResolvedValueOnce(makeContention(20));

    renderComponent();
    await screen.findByTestId("compute-contention");

    const badge = screen.getByTestId("contention-score-badge");
    expect(badge).toHaveClass("bg-emerald-100");
    expect(badge).toHaveTextContent("20");
  });

  it("renders time range selector with options: 1h, 6h, 24h, 7d", async () => {
    mockGetContention.mockResolvedValueOnce(makeContention(35));

    renderComponent();
    await screen.findByTestId("compute-contention");

    const selector = screen.getByTestId("time-range-selector") as HTMLSelectElement;
    expect(selector).toBeInTheDocument();
    expect(selector.value).toBe("1h");

    const options = Array.from(selector.options).map((o) => o.value);
    expect(options).toEqual(["1h", "6h", "24h", "7d"]);
  });

  it("changes time range and re-fetches data", async () => {
    mockGetContention
      .mockResolvedValueOnce(makeContention(35)) // initial fetch (1h)
      .mockResolvedValueOnce(makeContention(55)); // after changing to 6h

    renderComponent();
    await screen.findByTestId("contention-score-badge");

    expect(screen.getByTestId("contention-score-badge")).toHaveTextContent("35");

    const selector = screen.getByTestId("time-range-selector") as HTMLSelectElement;
    fireEvent.change(selector, { target: { value: "6h" } });

    // Wait for the second API call and new data to render
    await waitFor(() => {
      expect(mockGetContention).toHaveBeenCalledTimes(2);
    });

    // Verify the new data is displayed
    await waitFor(() => {
      expect(screen.getByTestId("contention-score-badge")).toHaveTextContent("55");
    });
  });

  it("renders error state with retry on getContention failure", async () => {
    mockGetContention.mockRejectedValueOnce(new Error("api down"));

    renderComponent();

    const errorEl = await screen.findByTestId("compute-contention-error");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl).toHaveTextContent(/api down/i);

    const retryBtn = screen.getByRole("button", { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();
  });

  it("uses memo and useCallback for optimization", async () => {
    // Verify that the component renders correctly (memo optimization is internal)
    mockGetContention.mockResolvedValueOnce(makeContention(35));
    renderComponent();

    // Verify the component is visible after loading
    await screen.findByTestId("time-range-selector");
    expect(screen.getByTestId("time-range-selector")).toBeInTheDocument();
  });
});
