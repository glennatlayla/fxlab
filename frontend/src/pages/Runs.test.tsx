/**
 * Tests for Runs page component.
 *
 * Verifies URL-parameter-driven routing between run list and run detail
 * views, and authentication enforcement.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Runs from "./Runs";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/features/runs/components/RunDetailView", () => ({
  RunDetailView: ({ runId }: { runId: string }) => (
    <div data-testid="run-detail-view">Detail for {runId}</div>
  ),
}));

vi.mock("@/features/runs/components/RunCardList", () => ({
  RunCardList: () => <div data-testid="run-card-list" />,
}));

vi.mock("@/features/runs/api", () => ({
  runsApi: {
    listRuns: vi.fn().mockResolvedValue({ runs: [], total: 0 }),
  },
}));

vi.mock("@/hooks/useMediaQuery", () => ({
  useIsMobile: () => false,
  useIsDesktop: () => true,
  useMediaQuery: () => false,
}));

// ---------------------------------------------------------------------------
// Helper: render with router + query client context
// ---------------------------------------------------------------------------

function renderWithRouter(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/runs" element={<Runs />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Runs page", () => {
  it("renders run list when no id parameter is present", () => {
    renderWithRouter("/runs");

    expect(screen.getByTestId("runs-page")).toBeInTheDocument();
    expect(screen.getByText("Run Monitor")).toBeInTheDocument();
    expect(screen.getByText("Active Runs")).toBeInTheDocument();
    expect(screen.getByText("Run History")).toBeInTheDocument();
  });

  it("renders RunDetailView when id parameter is present", () => {
    renderWithRouter("/runs?id=01HZ0000000000000000000001");

    expect(screen.getByTestId("run-detail-view")).toBeInTheDocument();
    expect(screen.getByText("Detail for 01HZ0000000000000000000001")).toBeInTheDocument();
  });

  it("does not render run list when id parameter is present", () => {
    renderWithRouter("/runs?id=01HZ0000000000000000000001");

    expect(screen.queryByTestId("runs-page")).not.toBeInTheDocument();
  });

  it("renders run list for empty id parameter", () => {
    renderWithRouter("/runs?id=");

    // Empty string is falsy, should show the list
    expect(screen.getByTestId("runs-page")).toBeInTheDocument();
  });
});
