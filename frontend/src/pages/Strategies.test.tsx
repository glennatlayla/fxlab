/**
 * Tests for the Strategies browse page (M2.D5).
 *
 * Verifies:
 *   1. The page renders the table when listStrategies returns rows.
 *   2. Empty state renders the "Import your first strategy" CTA when
 *      total_count is zero.
 *   3. Typing into the search box triggers a refetch with the new
 *      ``name_contains`` parameter.
 *   4. Changing the source select triggers a refetch with the new
 *      ``source`` parameter.
 *   5. Pagination Next / Prev buttons advance/retreat the page index
 *      and disable correctly at the bounds.
 *
 * Test strategy:
 *   - Mock @/api/strategies::listStrategies with vi.fn so each test
 *     controls the response queue.
 *   - Render the page inside a MemoryRouter so useNavigate and the
 *     <Link> components can resolve.
 *   - Stub @/auth/useAuth so the component renders without an
 *     AuthProvider tree.
 *
 * Example:
 *   npx vitest run src/pages/Strategies.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Strategies from "./Strategies";
import {
  ListStrategiesError,
  type StrategyListItem,
  type StrategyListPage,
} from "@/api/strategies";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/strategies", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/strategies")>();
  return {
    ...original,
    listStrategies: vi.fn(),
  };
});

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: "test-user", email: "trader@fxlab.test" },
    isAuthenticated: true,
    accessToken: "test-token",
    isLoading: false,
    logout: vi.fn(),
    login: vi.fn(),
    hasScope: vi.fn(() => true),
  }),
}));

import * as strategiesApi from "@/api/strategies";
const mockedListStrategies = strategiesApi.listStrategies as unknown as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeRow(overrides: Partial<StrategyListItem> = {}): StrategyListItem {
  return {
    id: "01HZ0000000000000000000001",
    name: "Bollinger Reversal",
    source: "ir_upload",
    version: "1.0.0",
    created_by: "01HZUSER000000000000000001",
    created_at: "2026-04-25T12:00:00Z",
    is_active: true,
    ...overrides,
  };
}

function makePage(overrides: Partial<StrategyListPage> = {}): StrategyListPage {
  const strategies = overrides.strategies ?? [makeRow()];
  return {
    strategies,
    page: 1,
    page_size: 20,
    total_count: strategies.length,
    total_pages: strategies.length === 0 ? 0 : 1,
    count: strategies.length,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Strategies />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Strategies browse page", () => {
  beforeEach(() => {
    mockedListStrategies.mockReset();
  });

  it("renders the table with rows from the mocked listStrategies response", async () => {
    mockedListStrategies.mockResolvedValueOnce(
      makePage({
        strategies: [
          makeRow({ id: "01ROW1", name: "RSI Reversion", source: "draft_form" }),
          makeRow({ id: "01ROW2", name: "Momentum Breakout", source: "ir_upload" }),
        ],
        total_count: 2,
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategies-table")).toBeInTheDocument();
    });

    // Both rows render with their names.
    expect(screen.getByText("RSI Reversion")).toBeInTheDocument();
    expect(screen.getByText("Momentum Breakout")).toBeInTheDocument();

    // Source pills render with the right copy.
    expect(screen.getAllByTestId("strategy-row-source-draft_form").length).toBeGreaterThanOrEqual(
      1,
    );
    expect(screen.getAllByTestId("strategy-row-source-ir_upload").length).toBeGreaterThanOrEqual(1);

    // Detail buttons exist per row and are wired with the row id.
    expect(screen.getByTestId("strategy-row-detail-01ROW1")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-row-detail-01ROW2")).toBeInTheDocument();
  });

  it("renders the empty state with the import CTA when no strategies exist", async () => {
    mockedListStrategies.mockResolvedValueOnce(
      makePage({ strategies: [], total_count: 0, total_pages: 0 }),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategies-empty")).toBeInTheDocument();
    });

    // The CTA links to the Strategy Studio import page.
    const cta = screen.getByTestId("strategies-empty-import-link") as HTMLAnchorElement;
    expect(cta.getAttribute("href")).toBe("/strategy-studio");
    expect(cta).toHaveTextContent(/import your first strategy/i);

    // The table is NOT rendered when the result set is empty.
    expect(screen.queryByTestId("strategies-table")).not.toBeInTheDocument();
  });

  it("triggers a refetch with name_contains when the user types in the search box", async () => {
    // Initial load returns one row; typing should trigger a second
    // listStrategies call carrying the new name_contains filter.
    mockedListStrategies.mockResolvedValue(makePage());

    renderPage();

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(1);
    });
    // First call has no filters.
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      name_contains: undefined,
    });

    fireEvent.change(screen.getByTestId("strategies-name-search"), {
      target: { value: "Bollinger" },
    });

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(2);
    });
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      name_contains: "Bollinger",
    });
  });

  it("triggers a refetch with source when the source filter changes", async () => {
    mockedListStrategies.mockResolvedValue(makePage());

    renderPage();

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(screen.getByTestId("strategies-source-filter"), {
      target: { value: "ir_upload" },
    });

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(2);
    });
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: "ir_upload",
      name_contains: undefined,
    });

    // Switching back to "all" drops the source filter.
    fireEvent.change(screen.getByTestId("strategies-source-filter"), {
      target: { value: "all" },
    });

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(3);
    });
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      name_contains: undefined,
    });
  });

  it("Next / Prev pagination advances and retreats the page index", async () => {
    // 3 pages worth of data; page 1, 2, 3 each return a fresh row set.
    mockedListStrategies
      .mockResolvedValueOnce(
        makePage({
          strategies: [makeRow({ id: "01PAGE1ROW", name: "Page 1 Row" })],
          page: 1,
          total_count: 3,
          total_pages: 3,
          page_size: 1,
          count: 1,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          strategies: [makeRow({ id: "01PAGE2ROW", name: "Page 2 Row" })],
          page: 2,
          total_count: 3,
          total_pages: 3,
          page_size: 1,
          count: 1,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          strategies: [makeRow({ id: "01PAGE1ROW", name: "Page 1 Row" })],
          page: 1,
          total_count: 3,
          total_pages: 3,
          page_size: 1,
          count: 1,
        }),
      );

    renderPage();

    // Initial load → Page 1
    await waitFor(() => {
      expect(screen.getByTestId("strategies-page-current")).toHaveTextContent("1");
    });
    // Prev is disabled on page 1.
    expect((screen.getByTestId("strategies-page-prev") as HTMLButtonElement).disabled).toBe(true);

    // Next → Page 2
    fireEvent.click(screen.getByTestId("strategies-page-next"));

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenLastCalledWith(2, 20, {
        source: undefined,
        name_contains: undefined,
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("strategies-page-current")).toHaveTextContent("2");
    });

    // Prev → Page 1
    fireEvent.click(screen.getByTestId("strategies-page-prev"));
    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
        source: undefined,
        name_contains: undefined,
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("strategies-page-current")).toHaveTextContent("1");
    });
  });

  it("renders a typed error banner when listStrategies rejects with ListStrategiesError", async () => {
    mockedListStrategies.mockRejectedValueOnce(
      new ListStrategiesError("Invalid filter value", 422),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategies-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("strategies-error")).toHaveTextContent(/invalid filter/i);
    // The table and empty state are suppressed when an error is showing.
    expect(screen.queryByTestId("strategies-table")).not.toBeInTheDocument();
    expect(screen.queryByTestId("strategies-empty")).not.toBeInTheDocument();
  });
});
