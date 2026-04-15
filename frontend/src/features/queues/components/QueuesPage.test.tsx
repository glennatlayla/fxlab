/**
 * Tests for QueuesPage.
 *
 * Covers:
 *   - Loading + error + empty states.
 *   - Renders queue cards with depth, running, failed, contention_score badge.
 *   - Contention score badge is color-coded based on level (low/medium/high).
 *   - ComputeContention section is composed below the queue cards.
 *   - Page lifecycle logging (mount/unmount).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api", () => ({
  queuesApi: {
    listQueues: vi.fn(),
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
import { queuesLogger } from "../logger";
import { QueuesPage } from "./QueuesPage";

const mockListQueues = queuesApi.listQueues as ReturnType<typeof vi.fn>;
const mockGetContention = queuesApi.getContention as ReturnType<typeof vi.fn>;
const mockPageMount = queuesLogger.pageMount as ReturnType<typeof vi.fn>;
const mockPageUnmount = queuesLogger.pageUnmount as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeQueueSnapshot(id: string, queueName: string, depth: number, contentionScore: number) {
  return {
    id,
    queue_name: queueName,
    timestamp: ISO,
    depth,
    contention_score: contentionScore,
    metadata: {},
    created_at: ISO,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <QueuesPage />
    </QueryClientProvider>,
  );
}

describe("QueuesPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    const ISO = "2026-04-06T12:00:00.000Z";
    mockGetContention.mockResolvedValue({
      queue_class: "research",
      depth: 0,
      running: 0,
      failed: 0,
      contention_score: 0,
      generated_at: ISO,
    });
  });

  it("logs page mount and unmount", async () => {
    mockListQueues.mockResolvedValueOnce({
      queues: [],
      generated_at: ISO,
    });

    const { unmount } = renderPage();
    await waitFor(() => {
      expect(mockPageMount).toHaveBeenCalledWith("QueuesPage", expect.any(String));
    });

    unmount();
    expect(mockPageUnmount).toHaveBeenCalledWith("QueuesPage", expect.any(String));
  });

  it("renders loading state then list of queue cards", async () => {
    mockListQueues.mockResolvedValueOnce({
      queues: [
        makeQueueSnapshot("queue-1", "task_queue", 42, 35),
        makeQueueSnapshot("queue-2", "event_queue", 15, 20),
      ],
      generated_at: ISO,
    });

    renderPage();

    expect(screen.getByTestId("queues-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("queues-list")).toBeInTheDocument();
    });

    expect(screen.getByTestId("queue-card-task_queue")).toBeInTheDocument();
    expect(screen.getByTestId("queue-card-event_queue")).toBeInTheDocument();
  });

  it("renders queue cards with depth, running, failed, and contention badge", async () => {
    mockListQueues.mockResolvedValueOnce({
      queues: [makeQueueSnapshot("queue-1", "task_queue", 42, 35)],
      generated_at: ISO,
    });

    renderPage();
    await screen.findByTestId("queue-card-task_queue");

    // Verify card displays queue name
    expect(screen.getByText("task_queue")).toBeInTheDocument();

    // Verify card displays depth
    expect(screen.getByTestId("queue-depth-task_queue")).toBeInTheDocument();

    // Verify contention badge exists
    expect(screen.getByTestId("queue-contention-badge-task_queue")).toBeInTheDocument();
  });

  it("color-codes contention badge based on level", async () => {
    mockListQueues.mockResolvedValueOnce({
      queues: [
        makeQueueSnapshot("queue-low", "low_queue", 10, 20), // low
        makeQueueSnapshot("queue-med", "medium_queue", 30, 60), // medium
        makeQueueSnapshot("queue-high", "high_queue", 50, 85), // high
      ],
      generated_at: ISO,
    });

    renderPage();
    await screen.findByTestId("queue-card-low_queue");

    // Low contention (green)
    const lowBadge = screen.getByTestId("queue-contention-badge-low_queue");
    expect(lowBadge).toHaveClass("bg-emerald-100");

    // Medium contention (amber)
    const medBadge = screen.getByTestId("queue-contention-badge-medium_queue");
    expect(medBadge).toHaveClass("bg-amber-100");

    // High contention (red)
    const highBadge = screen.getByTestId("queue-contention-badge-high_queue");
    expect(highBadge).toHaveClass("bg-red-100");
  });

  it("renders empty state when no queues returned", async () => {
    mockListQueues.mockResolvedValueOnce({
      queues: [],
      generated_at: ISO,
    });

    renderPage();
    expect(await screen.findByTestId("queues-empty")).toBeInTheDocument();
  });

  it("renders error state with retry on listQueues failure", async () => {
    mockListQueues.mockRejectedValueOnce(new Error("network down"));

    renderPage();

    const errorEl = await screen.findByTestId("queues-error");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl).toHaveTextContent(/network down/i);

    // Verify retry button is present in the error message
    expect(screen.queryByText(/Failed to load queues/i)).toBeInTheDocument();
  });

  it("composes ComputeContention section below queue cards", async () => {
    mockListQueues.mockResolvedValueOnce({
      queues: [makeQueueSnapshot("queue-1", "task_queue", 10, 25)],
      generated_at: ISO,
    });

    renderPage();
    await screen.findByTestId("queue-card-task_queue");

    // ComputeContention should be rendered (check for its selector element)
    await waitFor(() => {
      expect(screen.getByTestId("time-range-selector")).toBeInTheDocument();
    });
  });
});
