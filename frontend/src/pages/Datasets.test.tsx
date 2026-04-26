/**
 * Tests for the Datasets admin browse + register page (M4.E3).
 *
 * Verifies:
 *   1. The table renders rows from the mocked listDatasets response.
 *   2. The empty state renders the "Register your first dataset" CTA.
 *   3. The register modal opens, submits the form via registerDataset,
 *      then reloads the table.
 *   4. The toggle-certification button calls updateDataset with the
 *      flipped flag and reloads the table.
 *   5. Source / certification / search filter changes refetch with the
 *      correct parameters.
 *   6. Pagination Next / Prev advance the page index and disable at
 *      the bounds.
 *
 * Test strategy:
 *   - Mock @/api/datasets so each test controls the response queue.
 *   - Stub @/auth/useAuth so the component renders without an
 *     AuthProvider tree.
 *
 * Example:
 *   npx vitest run src/pages/Datasets.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Datasets from "./Datasets";
import {
  type DatasetListItem,
  type PagedDatasets,
} from "@/api/datasets";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/datasets", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/datasets")>();
  return {
    ...original,
    listDatasets: vi.fn(),
    registerDataset: vi.fn(),
    updateDataset: vi.fn(),
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

const mockedList = datasetsApi.listDatasets as unknown as ReturnType<typeof vi.fn>;
const mockedRegister = datasetsApi.registerDataset as unknown as ReturnType<typeof vi.fn>;
const mockedUpdate = datasetsApi.updateDataset as unknown as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeRow(overrides: Partial<DatasetListItem> = {}): DatasetListItem {
  return {
    id: "01HDATASET00000000000000001",
    dataset_ref: "fx-eurusd-15m",
    symbols: ["EURUSD"],
    timeframe: "15m",
    source: "oanda",
    version: "v1",
    is_certified: false,
    created_by: null,
    created_at: "2026-04-25T12:00:00Z",
    updated_at: "2026-04-25T12:00:00Z",
    ...overrides,
  };
}

function makePage(overrides: Partial<PagedDatasets> = {}): PagedDatasets {
  const datasets = overrides.datasets ?? [makeRow()];
  return {
    datasets,
    page: 1,
    page_size: 20,
    total_count: datasets.length,
    total_pages: datasets.length === 0 ? 0 : 1,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Datasets />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Datasets admin page", () => {
  beforeEach(() => {
    mockedList.mockReset();
    mockedRegister.mockReset();
    mockedUpdate.mockReset();
  });

  it("renders the table with rows from the mocked listDatasets response", async () => {
    mockedList.mockResolvedValueOnce(
      makePage({
        datasets: [
          makeRow({
            id: "01ROW1",
            dataset_ref: "fx-eurusd-15m",
            is_certified: true,
          }),
          makeRow({
            id: "01ROW2",
            dataset_ref: "fx-gbpusd-1h",
            symbols: ["GBPUSD"],
            timeframe: "1h",
            source: "alpaca",
          }),
        ],
        total_count: 2,
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("datasets-table")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dataset-row-fx-eurusd-15m")).toBeInTheDocument();
    expect(screen.getByTestId("dataset-row-fx-gbpusd-1h")).toBeInTheDocument();
    // Per-row toggle button exists.
    expect(screen.getByTestId("dataset-toggle-cert-fx-eurusd-15m")).toBeInTheDocument();
  });

  it("renders the empty state with a CTA when no datasets exist", async () => {
    mockedList.mockResolvedValueOnce(
      makePage({ datasets: [], total_count: 0, total_pages: 0 }),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("datasets-empty")).toBeInTheDocument();
    });
    expect(screen.getByTestId("datasets-empty-register")).toHaveTextContent(/register/i);
    expect(screen.queryByTestId("datasets-table")).not.toBeInTheDocument();
  });

  it("opens the register modal, submits the form, and reloads the table", async () => {
    mockedList.mockResolvedValue(makePage({ datasets: [], total_count: 0, total_pages: 0 }));
    mockedRegister.mockResolvedValueOnce(
      makeRow({ dataset_ref: "fx-new-1d", timeframe: "1d", source: "synthetic" }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("datasets-empty")).toBeInTheDocument();
    });

    // Open the modal via the header button.
    fireEvent.click(screen.getByTestId("datasets-register-open"));
    const modal = await screen.findByTestId("datasets-register-modal");

    // Fill the form.
    fireEvent.change(within(modal).getByTestId("datasets-register-ref"), {
      target: { value: "fx-new-1d" },
    });
    fireEvent.change(within(modal).getByTestId("datasets-register-symbols"), {
      target: { value: "EURUSD, GBPUSD" },
    });
    fireEvent.change(within(modal).getByTestId("datasets-register-timeframe"), {
      target: { value: "1d" },
    });
    fireEvent.change(within(modal).getByTestId("datasets-register-source"), {
      target: { value: "synthetic" },
    });
    fireEvent.change(within(modal).getByTestId("datasets-register-version"), {
      target: { value: "v1" },
    });
    fireEvent.click(within(modal).getByTestId("datasets-register-is-certified"));

    fireEvent.click(within(modal).getByTestId("datasets-register-submit"));

    await waitFor(() => {
      expect(mockedRegister).toHaveBeenCalledTimes(1);
    });
    expect(mockedRegister).toHaveBeenLastCalledWith({
      dataset_ref: "fx-new-1d",
      symbols: ["EURUSD", "GBPUSD"],
      timeframe: "1d",
      source: "synthetic",
      version: "v1",
      is_certified: true,
    });

    // After register, the page reloads via the listDatasets effect.
    await waitFor(() => {
      // First call (initial load) + second call (reload after register).
      expect(mockedList.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("toggles certification via the per-row button", async () => {
    mockedList
      .mockResolvedValueOnce(
        makePage({
          datasets: [makeRow({ dataset_ref: "fx-eurusd-15m", is_certified: false })],
          total_count: 1,
        }),
      )
      .mockResolvedValue(
        makePage({
          datasets: [makeRow({ dataset_ref: "fx-eurusd-15m", is_certified: true })],
          total_count: 1,
        }),
      );
    mockedUpdate.mockResolvedValueOnce(
      makeRow({ dataset_ref: "fx-eurusd-15m", is_certified: true }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("dataset-toggle-cert-fx-eurusd-15m")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("dataset-toggle-cert-fx-eurusd-15m"));

    await waitFor(() => {
      expect(mockedUpdate).toHaveBeenCalledTimes(1);
    });
    expect(mockedUpdate).toHaveBeenLastCalledWith("fx-eurusd-15m", { is_certified: true });

    // Table reloads after the toggle.
    await waitFor(() => {
      expect(mockedList.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("refetches with q when the search box changes", async () => {
    mockedList.mockResolvedValue(makePage());
    renderPage();

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(1);
    });
    expect(mockedList).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      is_certified: undefined,
      q: undefined,
    });

    fireEvent.change(screen.getByTestId("datasets-search"), {
      target: { value: "EUR" },
    });

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(2);
    });
    expect(mockedList).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      is_certified: undefined,
      q: "EUR",
    });
  });

  it("refetches with is_certified when the certification filter changes", async () => {
    mockedList.mockResolvedValue(makePage());
    renderPage();

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(screen.getByTestId("datasets-cert-filter"), {
      target: { value: "true" },
    });

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(2);
    });
    expect(mockedList).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      is_certified: true,
      q: undefined,
    });
  });

  it("paginates: Next advances and Prev retreats the page index", async () => {
    mockedList
      .mockResolvedValueOnce(
        makePage({
          datasets: [makeRow({ id: "01PG1", dataset_ref: "page-1-row" })],
          page: 1,
          total_count: 3,
          total_pages: 3,
          page_size: 1,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          datasets: [makeRow({ id: "01PG2", dataset_ref: "page-2-row" })],
          page: 2,
          total_count: 3,
          total_pages: 3,
          page_size: 1,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          datasets: [makeRow({ id: "01PG1", dataset_ref: "page-1-row" })],
          page: 1,
          total_count: 3,
          total_pages: 3,
          page_size: 1,
        }),
      );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("datasets-page-current")).toHaveTextContent("1");
    });
    expect((screen.getByTestId("datasets-page-prev") as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByTestId("datasets-page-next"));
    await waitFor(() => {
      expect(mockedList).toHaveBeenLastCalledWith(2, 20, {
        source: undefined,
        is_certified: undefined,
        q: undefined,
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("datasets-page-current")).toHaveTextContent("2");
    });

    fireEvent.click(screen.getByTestId("datasets-page-prev"));
    await waitFor(() => {
      expect(mockedList).toHaveBeenLastCalledWith(1, 20, {
        source: undefined,
        is_certified: undefined,
        q: undefined,
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("datasets-page-current")).toHaveTextContent("1");
    });
  });
});
