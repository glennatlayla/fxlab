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
  CloneStrategyError,
  ListStrategiesError,
  type ClonedStrategy,
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
    cloneStrategy: vi.fn(),
    archiveStrategy: vi.fn(),
    restoreStrategy: vi.fn(),
  };
});

// react-router-dom navigate is captured into a vi.fn so the clone-flow
// tests can assert the post-success navigation target without rendering
// a full route tree.
const navigateMock = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...original,
    useNavigate: () => navigateMock,
  };
});

// react-hot-toast is fired on success / unexpected errors. Stub the
// surface area we use so the test can verify the call without rendering
// a real toaster.
const toastSuccessMock = vi.fn();
const toastErrorMock = vi.fn();
vi.mock("react-hot-toast", () => ({
  default: {
    success: (msg: string) => toastSuccessMock(msg),
    error: (msg: string) => toastErrorMock(msg),
  },
  toast: {
    success: (msg: string) => toastSuccessMock(msg),
    error: (msg: string) => toastErrorMock(msg),
  },
}));

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
const mockedCloneStrategy = strategiesApi.cloneStrategy as unknown as ReturnType<typeof vi.fn>;
const mockedArchiveStrategy = strategiesApi.archiveStrategy as unknown as ReturnType<typeof vi.fn>;
const mockedRestoreStrategy = strategiesApi.restoreStrategy as unknown as ReturnType<typeof vi.fn>;

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
    mockedCloneStrategy.mockReset();
    mockedArchiveStrategy.mockReset();
    mockedRestoreStrategy.mockReset();
    navigateMock.mockReset();
    toastSuccessMock.mockReset();
    toastErrorMock.mockReset();
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

  // -------------------------------------------------------------------
  // Clone flow (POST /strategies/{id}/clone)
  // -------------------------------------------------------------------

  function makeClone(overrides: Partial<ClonedStrategy> = {}): ClonedStrategy {
    return {
      id: "01HCLONE0000000000000000001",
      name: "Bollinger Reversal (copy)",
      code: "{}",
      version: "1.0.0",
      source: "ir_upload",
      created_by: "01HUSER000000000000000001",
      is_active: true,
      row_version: 1,
      created_at: "2026-04-25T12:30:00Z",
      updated_at: "2026-04-25T12:30:00Z",
      ...overrides,
    };
  }

  async function openCloneModalForFirstRow(): Promise<{
    rowId: string;
    rowName: string;
  }> {
    const row = makeRow({
      id: "01ROWCLONESRC",
      name: "Bollinger Reversal",
    });
    mockedListStrategies.mockResolvedValue(makePage({ strategies: [row] }));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategies-table")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId(`strategy-row-clone-${row.id}`));

    await waitFor(() => {
      expect(screen.getByTestId("strategies-clone-modal")).toBeInTheDocument();
    });

    return { rowId: row.id, rowName: row.name };
  }

  it("renders a Clone button on each row that opens the clone modal pre-filled with '{name} (copy)'", async () => {
    const { rowId, rowName } = await openCloneModalForFirstRow();

    // Modal title carries the source name so the operator knows what
    // they are cloning.
    expect(screen.getByTestId("strategies-clone-modal")).toHaveTextContent(rowName);

    // Name input is pre-filled with "<source name> (copy)".
    const input = screen.getByTestId("strategies-clone-name-input") as HTMLInputElement;
    expect(input.value).toBe(`${rowName} (copy)`);

    // Cancel + Clone buttons exist.
    expect(screen.getByTestId("strategies-clone-cancel")).toBeInTheDocument();
    expect(screen.getByTestId("strategies-clone-submit")).toBeInTheDocument();

    // Sanity — the source row id is wired into the submit handler. The
    // assertion fires when the user clicks Clone and the API is called
    // with the source id (covered by the next test).
    expect(rowId).toBe("01ROWCLONESRC");
  });

  it("submitting Clone calls cloneStrategy and navigates to /strategy-studio/{newId}", async () => {
    const { rowId } = await openCloneModalForFirstRow();
    const cloneRecord = makeClone({ id: "01HCLONENEW00000000000001" });
    mockedCloneStrategy.mockResolvedValueOnce(cloneRecord);

    fireEvent.click(screen.getByTestId("strategies-clone-submit"));

    await waitFor(() => {
      expect(mockedCloneStrategy).toHaveBeenCalledTimes(1);
    });
    expect(mockedCloneStrategy).toHaveBeenCalledWith(rowId, "Bollinger Reversal (copy)");

    // Navigation target on success — matches the import-IR / detail flow
    // (the operator lands on the same page they would land on after
    // importing a fresh IR).
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/strategy-studio/01HCLONENEW00000000000001");
    });

    // Success toast was fired so the operator gets the standard
    // confirmation banner.
    expect(toastSuccessMock).toHaveBeenCalled();

    // Modal is dismissed after a successful clone.
    await waitFor(() => {
      expect(screen.queryByTestId("strategies-clone-modal")).not.toBeInTheDocument();
    });
  });

  it("shows an inline error and stays open when cloneStrategy returns 409", async () => {
    await openCloneModalForFirstRow();
    mockedCloneStrategy.mockRejectedValueOnce(
      new CloneStrategyError('A strategy named "Bollinger Reversal (copy)" already exists', 409),
    );

    fireEvent.click(screen.getByTestId("strategies-clone-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("strategies-clone-name-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("strategies-clone-name-error")).toHaveTextContent(/already exists/i);

    // Modal stays open so the operator can edit the name and retry
    // without re-opening it.
    expect(screen.getByTestId("strategies-clone-modal")).toBeInTheDocument();

    // Navigation did NOT fire on the 409 path.
    expect(navigateMock).not.toHaveBeenCalled();
    // Success toast did NOT fire.
    expect(toastSuccessMock).not.toHaveBeenCalled();
  });

  it("shows an inline validation error when the user submits an empty name", async () => {
    await openCloneModalForFirstRow();

    const input = screen.getByTestId("strategies-clone-name-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByTestId("strategies-clone-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("strategies-clone-name-error")).toBeInTheDocument();
    });
    // No API call when client-side validation fails.
    expect(mockedCloneStrategy).not.toHaveBeenCalled();
  });

  it("clicking Cancel dismisses the clone modal without firing the API", async () => {
    await openCloneModalForFirstRow();
    fireEvent.click(screen.getByTestId("strategies-clone-cancel"));

    await waitFor(() => {
      expect(screen.queryByTestId("strategies-clone-modal")).not.toBeInTheDocument();
    });
    expect(mockedCloneStrategy).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------
  // Archive / restore lifecycle (POST /strategies/{id}/archive | restore)
  // -------------------------------------------------------------------

  function makeArchivedRecord(
    overrides: Partial<{
      id: string;
      name: string;
      archived_at: string | null;
      row_version: number;
    }> = {},
  ) {
    return {
      id: "01ROWARCHIVE000000000000A",
      name: "Bollinger Reversal",
      code: "{}",
      version: "1.0.0",
      source: "ir_upload" as const,
      created_by: "01HUSER000000000000000001",
      is_active: true,
      row_version: 2,
      archived_at: "2026-04-26T18:53:34+00:00",
      created_at: "2026-04-25T12:00:00Z",
      updated_at: "2026-04-26T18:53:34+00:00",
      ...overrides,
    };
  }

  it("renders Archive button only on active rows; clicking opens confirm and calls archiveStrategy", async () => {
    const activeRow = makeRow({
      id: "01ROWACTIVE000000000000A",
      name: "Active Strategy",
      archived_at: null,
    });
    mockedListStrategies.mockResolvedValue(makePage({ strategies: [activeRow] }));
    mockedArchiveStrategy.mockResolvedValueOnce(
      makeArchivedRecord({ id: activeRow.id, name: activeRow.name }),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("strategies-table")).toBeInTheDocument();
    });

    // Archive button visible; Restore is not.
    expect(screen.getByTestId(`strategy-row-archive-${activeRow.id}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`strategy-row-restore-${activeRow.id}`)).not.toBeInTheDocument();

    // Open the confirm dialog.
    fireEvent.click(screen.getByTestId(`strategy-row-archive-${activeRow.id}`));
    await waitFor(() => {
      expect(screen.getByTestId("strategies-archive-modal")).toBeInTheDocument();
    });
    expect(screen.getByTestId("strategies-archive-dialog-body")).toHaveTextContent(
      /will be hidden from the default list but kept for audit/i,
    );

    // Confirm fires the API.
    fireEvent.click(screen.getByTestId("strategies-archive-confirm"));

    await waitFor(() => {
      expect(mockedArchiveStrategy).toHaveBeenCalledTimes(1);
    });
    expect(mockedArchiveStrategy).toHaveBeenCalledWith(activeRow.id);

    // Success toast + refetch (initial + post-archive = 2 list calls).
    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(2);
    });
    // Modal dismissed.
    await waitFor(() => {
      expect(screen.queryByTestId("strategies-archive-modal")).not.toBeInTheDocument();
    });
  });

  it("renders Restore button only on archived rows; clicking opens confirm and calls restoreStrategy", async () => {
    const archivedRow = makeRow({
      id: "01ROWARCH000000000000000B",
      name: "Archived Strategy",
      archived_at: "2026-04-26T18:53:34+00:00",
    });
    mockedListStrategies.mockResolvedValue(makePage({ strategies: [archivedRow] }));
    mockedRestoreStrategy.mockResolvedValueOnce(
      makeArchivedRecord({
        id: archivedRow.id,
        name: archivedRow.name,
        archived_at: null,
        row_version: 3,
      }),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("strategies-table")).toBeInTheDocument();
    });

    // The Archived badge renders inline next to the source pill.
    expect(screen.getByTestId(`strategy-row-archived-badge-${archivedRow.id}`)).toBeInTheDocument();

    // Restore button visible; Archive is not.
    expect(screen.getByTestId(`strategy-row-restore-${archivedRow.id}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`strategy-row-archive-${archivedRow.id}`)).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId(`strategy-row-restore-${archivedRow.id}`));
    await waitFor(() => {
      expect(screen.getByTestId("strategies-archive-modal")).toBeInTheDocument();
    });
    expect(screen.getByTestId("strategies-archive-dialog-body")).toHaveTextContent(
      /restore .* to active list/i,
    );

    fireEvent.click(screen.getByTestId("strategies-archive-confirm"));
    await waitFor(() => {
      expect(mockedRestoreStrategy).toHaveBeenCalledTimes(1);
    });
    expect(mockedRestoreStrategy).toHaveBeenCalledWith(archivedRow.id);

    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(2);
    });
  });

  it("toggling 'Show archived' refetches with includeArchived=true", async () => {
    mockedListStrategies.mockResolvedValue(makePage());
    renderPage();

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(1);
    });
    // First call has includeArchived undefined (falsy → omitted server-side).
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      name_contains: undefined,
      includeArchived: undefined,
    });

    fireEvent.click(screen.getByTestId("strategies-show-archived"));

    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(2);
    });
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      name_contains: undefined,
      includeArchived: true,
    });

    // Toggle back off — request reverts to the default-omitted shape.
    fireEvent.click(screen.getByTestId("strategies-show-archived"));
    await waitFor(() => {
      expect(mockedListStrategies).toHaveBeenCalledTimes(3);
    });
    expect(mockedListStrategies).toHaveBeenLastCalledWith(1, 20, {
      source: undefined,
      name_contains: undefined,
      includeArchived: undefined,
    });
  });

  it("Cancel on the archive dialog dismisses without firing the API", async () => {
    const activeRow = makeRow({
      id: "01ROWCANCELARCH000000000C",
      archived_at: null,
    });
    mockedListStrategies.mockResolvedValue(makePage({ strategies: [activeRow] }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("strategies-table")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId(`strategy-row-archive-${activeRow.id}`));
    await waitFor(() => {
      expect(screen.getByTestId("strategies-archive-modal")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("strategies-archive-cancel"));
    await waitFor(() => {
      expect(screen.queryByTestId("strategies-archive-modal")).not.toBeInTheDocument();
    });
    expect(mockedArchiveStrategy).not.toHaveBeenCalled();
  });
});
