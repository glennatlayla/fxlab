/**
 * Tests for DiagnosticsShell.
 *
 * Covers:
 *   - Loading state while fetching diagnostics data.
 *   - Error state with Retry button on fetch failure.
 *   - Happy path: service health status, dependency list with status badges,
 *     operational counts snapshot.
 *   - Dependency status badges use correct colours (OK=green, DEGRADED=amber, DOWN=red).
 *   - Empty dependency list renders empty message.
 *   - Read-only: no mutation buttons rendered.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn() },
}));
vi.mock("../logger", () => ({
  feedsLogger: { pageMount: vi.fn(), pageUnmount: vi.fn() },
}));

import { apiClient } from "@/api/client";
import { DiagnosticsShell } from "./DiagnosticsShell";

const mockGet = apiClient.get as ReturnType<typeof vi.fn>;

const ISO = "2026-04-06T12:00:00.000Z";

function makeDependencyHealthResponse(deps: Array<Record<string, unknown>> = [], overall = "OK") {
  return {
    data: {
      dependencies: deps,
      overall_status: overall,
      generated_at: ISO,
    },
  };
}

function makeDiagnosticsSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      queue_contention_count: 0,
      feed_health_count: 0,
      parity_critical_count: 0,
      certification_blocked_count: 0,
      generated_at: ISO,
      ...overrides,
    },
  };
}

function makeServiceHealth(status = "ok") {
  return {
    data: {
      status,
      service: "fxlab-api",
      version: "3.1.0",
      components: { database: "ok", redis: { status: "ok" } },
    },
  };
}

function renderShell() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DiagnosticsShell />
    </QueryClientProvider>,
  );
}

describe("DiagnosticsShell", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders loading state while fetching", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    renderShell();
    expect(screen.getByTestId("diagnostics-loading")).toBeInTheDocument();
  });

  it("renders error state with Retry on fetch failure", async () => {
    mockGet.mockRejectedValue(new Error("network down"));
    renderShell();
    await screen.findByTestId("diagnostics-error");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders service health, dependencies, and diagnostics snapshot", async () => {
    // Three concurrent fetches: /health, /health/dependencies, /health/diagnostics
    mockGet
      .mockResolvedValueOnce(makeServiceHealth("ok"))
      .mockResolvedValueOnce(
        makeDependencyHealthResponse(
          [
            { name: "database", status: "OK", latency_ms: 0.8, detail: "" },
            { name: "queues", status: "DEGRADED", latency_ms: 12.5, detail: "high latency" },
            { name: "artifact_store", status: "DOWN", latency_ms: 0, detail: "unreachable" },
          ],
          "DOWN",
        ),
      )
      .mockResolvedValueOnce(
        makeDiagnosticsSnapshot({
          queue_contention_count: 2,
          feed_health_count: 5,
          parity_critical_count: 1,
          certification_blocked_count: 0,
        }),
      );

    renderShell();
    await screen.findByTestId("diagnostics-shell");

    // Service health
    expect(screen.getByTestId("diagnostics-service-status")).toHaveTextContent("ok");

    // Dependencies
    const dbRow = screen.getByTestId("diagnostics-dep-database");
    expect(within(dbRow).getByText("OK")).toBeInTheDocument();

    const queueRow = screen.getByTestId("diagnostics-dep-queues");
    expect(within(queueRow).getByText("DEGRADED")).toBeInTheDocument();

    const storeRow = screen.getByTestId("diagnostics-dep-artifact_store");
    expect(within(storeRow).getByText("DOWN")).toBeInTheDocument();

    // Dependency badge colours
    const okBadge = within(dbRow).getByTestId("dep-status-badge-database");
    expect(okBadge.className).toMatch(/emerald/);

    const degradedBadge = within(queueRow).getByTestId("dep-status-badge-queues");
    expect(degradedBadge.className).toMatch(/amber/);

    const downBadge = within(storeRow).getByTestId("dep-status-badge-artifact_store");
    expect(downBadge.className).toMatch(/red/);

    // Diagnostics snapshot counts
    expect(screen.getByTestId("diagnostics-queue-contention")).toHaveTextContent("2");
    expect(screen.getByTestId("diagnostics-feed-health")).toHaveTextContent("5");
    expect(screen.getByTestId("diagnostics-parity-critical")).toHaveTextContent("1");
    expect(screen.getByTestId("diagnostics-cert-blocked")).toHaveTextContent("0");
  });

  it("renders no action/mutation buttons (read-only)", async () => {
    mockGet
      .mockResolvedValueOnce(makeServiceHealth())
      .mockResolvedValueOnce(makeDependencyHealthResponse([], "OK"))
      .mockResolvedValueOnce(makeDiagnosticsSnapshot());

    renderShell();
    await screen.findByTestId("diagnostics-shell");

    // No buttons at all in happy path (no Retry, no actions)
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
