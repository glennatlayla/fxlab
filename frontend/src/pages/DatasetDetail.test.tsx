/**
 * Tests for the DatasetDetail admin page.
 *
 * Verifies:
 *   1. Renders all four sections (header, bar inventory, strategies-using,
 *      recent runs) when the API returns a full payload.
 *   2. Empty bar_inventory + zero-row inventory both render the
 *      "No bars ingested yet" empty state.
 *   3. A 404 response renders the "Dataset not found" surface.
 *   4. Generic errors render the typed error banner.
 *   5. Strategies-using and recent-runs lists link to the right routes.
 *
 * Test strategy:
 *   - Mock @/api/datasets so each test controls the response queue.
 *   - Stub @/auth/useAuth so the component renders without an
 *     AuthProvider tree.
 *   - Render inside a MemoryRouter at /admin/datasets/:ref so useParams
 *     resolves correctly.
 *
 * Example:
 *   npx vitest run src/pages/DatasetDetail.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DatasetDetail from "./DatasetDetail";
import { DatasetsApiError, type DatasetDetail as DatasetDetailRecord } from "@/api/datasets";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/datasets", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/datasets")>();
  return {
    ...original,
    getDatasetDetail: vi.fn(),
  };
});

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: "test-user", email: "admin@fxlab.test" },
    isAuthenticated: true,
    accessToken: "test-token",
    isLoading: false,
    logout: vi.fn(),
    login: vi.fn(),
    hasScope: vi.fn(() => true),
  }),
}));

import * as datasetsApi from "@/api/datasets";

const mockedGetDetail = datasetsApi.getDatasetDetail as unknown as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeDetail(overrides: Partial<DatasetDetailRecord> = {}): DatasetDetailRecord {
  return {
    dataset_ref: "fx-eurusd-15m",
    dataset_id: "01HDATASET00000000000000001",
    symbols: ["EURUSD"],
    timeframe: "15m",
    source: "oanda",
    version: "v1",
    is_certified: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-04-25T12:00:00Z",
    bar_inventory: [
      {
        symbol: "EURUSD",
        timeframe: "15m",
        row_count: 1234,
        min_ts: "2026-01-01T00:00:00Z",
        max_ts: "2026-04-25T23:45:00Z",
      },
    ],
    strategies_using: [
      {
        strategy_id: "01HSTRAT00000000000000000A",
        name: "EURUSD MACD",
        last_used_at: "2026-04-25T14:30:00Z",
      },
    ],
    recent_runs: [
      {
        run_id: "01HRUN00000000000000000001",
        strategy_id: "01HSTRAT00000000000000000A",
        status: "completed",
        completed_at: "2026-04-25T14:30:00Z",
      },
    ],
    ...overrides,
  };
}

function renderPage(ref: string = "fx-eurusd-15m") {
  return render(
    <MemoryRouter initialEntries={[`/admin/datasets/${ref}`]}>
      <Routes>
        <Route path="/admin/datasets/:ref" element={<DatasetDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DatasetDetail page", () => {
  beforeEach(() => {
    mockedGetDetail.mockReset();
  });

  it("renders all four sections when the API returns a full payload", async () => {
    mockedGetDetail.mockResolvedValueOnce(makeDetail());
    renderPage();

    // Header
    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-page")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dataset-detail-ref")).toHaveTextContent("fx-eurusd-15m");
    expect(screen.getByTestId("dataset-detail-cert-true")).toBeInTheDocument();
    const meta = screen.getByTestId("dataset-detail-meta");
    expect(meta).toHaveTextContent("EURUSD");
    expect(meta).toHaveTextContent("oanda");

    // Bar inventory
    expect(screen.getByTestId("dataset-detail-inventory-table")).toBeInTheDocument();
    const inventoryRow = screen.getByTestId("dataset-detail-inventory-row-EURUSD");
    expect(inventoryRow).toHaveTextContent("EURUSD");
    expect(inventoryRow).toHaveTextContent("1,234");

    // Strategies-using
    expect(screen.getByTestId("dataset-detail-strategies-list")).toBeInTheDocument();
    const stratLink = screen.getByTestId("dataset-detail-strategy-link-01HSTRAT00000000000000000A");
    expect(stratLink).toHaveAttribute("href", "/strategy-studio/01HSTRAT00000000000000000A");
    expect(stratLink).toHaveTextContent("EURUSD MACD");

    // Recent runs
    expect(screen.getByTestId("dataset-detail-runs-list")).toBeInTheDocument();
    const runLink = screen.getByTestId("dataset-detail-run-link-01HRUN00000000000000000001");
    expect(runLink).toHaveAttribute("href", "/runs/01HRUN00000000000000000001/results");
    expect(screen.getByTestId("run-status-completed")).toBeInTheDocument();
  });

  it("renders the empty state copy when bar_inventory is empty", async () => {
    mockedGetDetail.mockResolvedValueOnce(
      makeDetail({
        bar_inventory: [],
      }),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-inventory-empty")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dataset-detail-inventory-empty")).toHaveTextContent(
      "No bars ingested yet for this dataset.",
    );
    expect(screen.queryByTestId("dataset-detail-inventory-table")).not.toBeInTheDocument();
  });

  it("renders the empty state when every inventory row has zero rows", async () => {
    mockedGetDetail.mockResolvedValueOnce(
      makeDetail({
        bar_inventory: [
          {
            symbol: "EURUSD",
            timeframe: "15m",
            row_count: 0,
            min_ts: null,
            max_ts: null,
          },
        ],
      }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-inventory-empty")).toBeInTheDocument();
    });
  });

  it("renders empty-state copy in the strategies and runs sections when both are empty", async () => {
    mockedGetDetail.mockResolvedValueOnce(
      makeDetail({
        strategies_using: [],
        recent_runs: [],
      }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-strategies-empty")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dataset-detail-runs-empty")).toBeInTheDocument();
  });

  it("renders the 'Dataset not found' surface on a 404", async () => {
    mockedGetDetail.mockRejectedValueOnce(
      new DatasetsApiError(
        "Dataset 'fx-missing' not registered.",
        404,
        "Dataset 'fx-missing' not registered.",
      ),
    );
    renderPage("fx-missing");
    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-not-found")).toBeInTheDocument();
    });
    const notFound = screen.getByTestId("dataset-detail-not-found");
    expect(notFound).toHaveTextContent("Dataset not found");
    expect(notFound).toHaveTextContent("fx-missing");
    // Back link points to the parent listing page.
    const backLink = within(notFound).getByTestId("dataset-detail-back-link");
    expect(backLink).toHaveAttribute("href", "/admin/datasets");
  });

  it("renders a generic error banner on non-404 failures", async () => {
    mockedGetDetail.mockRejectedValueOnce(
      new DatasetsApiError("Internal server error", 500, "Internal server error"),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dataset-detail-error")).toHaveTextContent("Internal server error");
  });

  it("renders the loading skeletons before the API resolves", async () => {
    let resolveLater: (value: DatasetDetailRecord) => void = () => {};
    mockedGetDetail.mockImplementationOnce(
      () =>
        new Promise<DatasetDetailRecord>((resolve) => {
          resolveLater = resolve;
        }),
    );
    renderPage();
    expect(screen.getByTestId("dataset-detail-loading")).toBeInTheDocument();
    expect(screen.getByTestId("dataset-detail-skeleton-header")).toBeInTheDocument();
    expect(screen.getByTestId("dataset-detail-skeleton-inventory")).toBeInTheDocument();
    expect(screen.getByTestId("dataset-detail-skeleton-strategies")).toBeInTheDocument();
    expect(screen.getByTestId("dataset-detail-skeleton-runs")).toBeInTheDocument();
    // Resolve so the test cleans up cleanly (no pending promise warnings).
    resolveLater(makeDetail());
    await waitFor(() => {
      expect(screen.getByTestId("dataset-detail-page")).toBeInTheDocument();
    });
  });
});
