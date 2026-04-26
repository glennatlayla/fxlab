/**
 * Tests for the StrategyDetail page (M2.D2 + M2.D3 wiring).
 *
 * Verifies:
 *   1. Loading state renders before the GET /strategies/{id} promise resolves.
 *   2. For source==="ir_upload" with a populated parsed_ir, the page renders
 *      :class:`IrDetailView` (the canonical IR view, sourced from a real
 *      production fixture file under ``Strategy Repo/``).
 *   3. The "Execute backtest" button is enabled for ir_upload strategies and
 *      opens :class:`RunBacktestModal` when clicked.
 *   4. For source==="draft_form", the draft fallback panel renders and the
 *      "Execute backtest" button is disabled (the modal needs a parsed IR).
 *   5. A 404 from the API surfaces a typed error banner.
 *
 * Test strategy:
 *   - Mock @/api/strategies::getStrategy so each test controls the response.
 *   - Render the page inside a MemoryRouter at ``/strategy-studio/:id``
 *     so useParams resolves correctly and the modal's useNavigate hook
 *     does not throw.
 *   - Stub useAuth so the route loads without an AuthProvider tree.
 *
 * Example:
 *   npx vitest run src/pages/StrategyDetail.test.tsx
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import StrategyDetail from "./StrategyDetail";
import {
  GetStrategyError,
  GetStrategyRunsError,
  type StrategyDetail as StrategyDetailRecord,
  type StrategyRunsPage,
} from "@/api/strategies";
import type { StrategyIR } from "@/types/strategy_ir";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/strategies", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/strategies")>();
  return {
    ...original,
    getStrategy: vi.fn(),
    getStrategyRuns: vi.fn(),
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

// Avoid the modal's submit-side dependency from spamming the test surface.
vi.mock("@/api/runs", () => ({
  submitRunFromIr: vi.fn(),
}));

// Pull the mocked getStrategy / getStrategyRuns references for per-test arrangement.
import * as strategiesApi from "@/api/strategies";
const mockedGetStrategy = strategiesApi.getStrategy as unknown as ReturnType<typeof vi.fn>;
const mockedGetStrategyRuns = strategiesApi.getStrategyRuns as unknown as ReturnType<typeof vi.fn>;

/**
 * Build an empty :class:`StrategyRunsPage` envelope for the recent-runs
 * mock. Use ``pageWith`` for non-empty pages.
 */
function emptyRunsPage(): StrategyRunsPage {
  return {
    runs: [],
    page: 1,
    page_size: 20,
    total_count: 0,
    total_pages: 0,
  };
}

/**
 * Build a populated :class:`StrategyRunsPage` envelope for the recent-runs
 * mock. The supplied row count drives ``total_count`` and ``total_pages``
 * so the test can exercise the "page X of Y" copy.
 */
function pageWithRuns(rows: StrategyRunsPage["runs"]): StrategyRunsPage {
  return {
    runs: rows,
    page: 1,
    page_size: 20,
    total_count: rows.length,
    total_pages: 1,
  };
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const STRATEGY_ID = "01HZ0000000000000000000001";

/**
 * Resolve the absolute path to a production IR file, relative to the
 * repo root. Mirrors :file:`IrDetailView.test.tsx` so we share the same
 * resolution rule for vitest's cwd (``<repo>/frontend``).
 */
function repoRoot(): string {
  const cwd = process.cwd();
  if (path.basename(cwd) === "frontend") return path.resolve(cwd, "..");
  return cwd;
}

function loadProductionIr(): StrategyIR {
  const rel =
    "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_SingleAsset_MeanReversion_H1.strategy_ir.json";
  const raw = readFileSync(path.join(repoRoot(), rel), "utf8");
  return JSON.parse(raw) as StrategyIR;
}

function makeIrUploadRecord(overrides: Partial<StrategyDetailRecord> = {}): StrategyDetailRecord {
  const ir = loadProductionIr();
  return {
    id: STRATEGY_ID,
    name: ir.metadata.strategy_name,
    code: JSON.stringify(ir),
    version: ir.metadata.strategy_version,
    source: "ir_upload",
    created_by: "01HZUSER000000000000000001",
    is_active: true,
    row_version: 1,
    created_at: "2026-04-25T12:00:00Z",
    updated_at: "2026-04-25T12:00:00Z",
    parsed_ir: ir,
    draft_fields: null,
    ...overrides,
  };
}

function makeDraftFormRecord(overrides: Partial<StrategyDetailRecord> = {}): StrategyDetailRecord {
  return {
    id: STRATEGY_ID,
    name: "Draft RSI Reversal",
    code: JSON.stringify({ name: "Draft RSI Reversal", entry_condition: "RSI(14) < 30" }),
    version: "1",
    source: "draft_form",
    created_by: "01HZUSER000000000000000001",
    is_active: true,
    row_version: 1,
    created_at: "2026-04-25T12:00:00Z",
    updated_at: "2026-04-25T12:00:00Z",
    parsed_ir: null,
    draft_fields: { name: "Draft RSI Reversal", entry_condition: "RSI(14) < 30" },
    ...overrides,
  };
}

/**
 * Render :class:`StrategyDetail` inside a MemoryRouter scoped to the
 * canonical route shape ``/strategy-studio/:id``.
 *
 * Args:
 *   id: The path parameter to seed (default: STRATEGY_ID).
 */
function renderPage(id: string = STRATEGY_ID) {
  return render(
    <MemoryRouter initialEntries={[`/strategy-studio/${id}`]}>
      <Routes>
        <Route path="/strategy-studio/:id" element={<StrategyDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StrategyDetail page", () => {
  beforeEach(() => {
    mockedGetStrategy.mockReset();
    mockedGetStrategyRuns.mockReset();
    // Default: every test that does not arrange recent-runs explicitly
    // gets an empty page so the section renders its empty-state without
    // the test having to opt in.
    mockedGetStrategyRuns.mockResolvedValue(emptyRunsPage());
  });

  it("shows a loading state while the GET /strategies/{id} call is in flight", async () => {
    // Never-resolving promise so the loading state stays visible.
    mockedGetStrategy.mockImplementation(() => new Promise(() => {}));

    renderPage();

    expect(screen.getByTestId("strategy-detail-loading")).toBeInTheDocument();
  });

  it("renders IrDetailView and an enabled Execute backtest button for ir_upload", async () => {
    mockedGetStrategy.mockResolvedValueOnce(makeIrUploadRecord());

    renderPage();

    // Wait for the page to swap from loading → loaded.
    await waitFor(() => {
      expect(screen.getByTestId("strategy-detail-page")).toBeInTheDocument();
    });

    // Header shows the canonical name + source pill.
    expect(screen.getByTestId("strategy-detail-name")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-detail-source")).toHaveTextContent(/imported ir/i);

    // The IR detail view renders (its own data-testid).
    expect(screen.getByTestId("ir-detail-view")).toBeInTheDocument();

    // Execute backtest is enabled.
    const button = screen.getByTestId("execute-backtest-button") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  it("opens RunBacktestModal when the Execute backtest button is clicked", async () => {
    mockedGetStrategy.mockResolvedValueOnce(makeIrUploadRecord());

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("execute-backtest-button")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("execute-backtest-button"));

    // Modal owns its own data-testid.
    expect(screen.getByTestId("run-backtest-modal")).toBeInTheDocument();
    // Strategy id is forwarded into the modal — the modal does not
    // expose strategyId as text, but the strategy_ref fields should be
    // present (proving the modal mounted and seeded its empty plan).
    expect(screen.getByTestId("field-strategy_ref.strategy_name")).toBeInTheDocument();
  });

  it("renders the draft fallback panel and disables Execute backtest for draft_form", async () => {
    mockedGetStrategy.mockResolvedValueOnce(makeDraftFormRecord());

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategy-detail-page")).toBeInTheDocument();
    });

    // Draft panel renders, IR view does NOT.
    expect(screen.getByTestId("strategy-detail-draft-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("ir-detail-view")).not.toBeInTheDocument();

    // The button is mounted (so the operator sees the affordance) but
    // disabled to communicate that backtest is not available here.
    const button = screen.getByTestId("execute-backtest-button") as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    // Source pill shows the alternate label.
    expect(screen.getByTestId("strategy-detail-source")).toHaveTextContent(/draft form/i);

    // Clicking the disabled button should not mount the modal.
    fireEvent.click(button);
    expect(screen.queryByTestId("run-backtest-modal")).not.toBeInTheDocument();
  });

  it("shows a 404 error banner when the strategy is not found", async () => {
    mockedGetStrategy.mockRejectedValueOnce(
      new GetStrategyError(`Strategy ${STRATEGY_ID} not found`, 404),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategy-detail-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("strategy-detail-error")).toHaveTextContent(/not found/i);
    // The page does not render the loaded body.
    expect(screen.queryByTestId("strategy-detail-page")).not.toBeInTheDocument();
  });

  it("shows a 422 error banner when the stored IR fails re-validation", async () => {
    mockedGetStrategy.mockRejectedValueOnce(
      new GetStrategyError("Validation error: missing field 'metadata'", 422),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("strategy-detail-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("strategy-detail-error")).toHaveTextContent(/re-validation/i);
  });

  // ---------------------------------------------------------------------
  // Recent runs section
  // ---------------------------------------------------------------------

  describe("Recent runs section", () => {
    it("renders the empty state when the strategy has no runs", async () => {
      mockedGetStrategy.mockResolvedValueOnce(makeIrUploadRecord());
      // Default beforeEach() arrangement already returns emptyRunsPage(),
      // but pin it here for self-contained readability.
      mockedGetStrategyRuns.mockResolvedValueOnce(emptyRunsPage());

      renderPage();

      await waitFor(() => {
        expect(screen.getByTestId("strategy-detail-page")).toBeInTheDocument();
      });

      // The section mounts with the page body.
      expect(screen.getByTestId("strategy-recent-runs")).toBeInTheDocument();

      // Empty state appears once the GET resolves.
      await waitFor(() => {
        expect(screen.getByTestId("strategy-recent-runs-empty")).toBeInTheDocument();
      });

      // No table rows rendered.
      expect(screen.queryByTestId(/^recent-run-row-/)).not.toBeInTheDocument();
      // The endpoint was called with the strategy id.
      expect(mockedGetStrategyRuns).toHaveBeenCalledWith(STRATEGY_ID, 1, 20);
    });

    it("renders one row per run when the API returns data", async () => {
      mockedGetStrategy.mockResolvedValueOnce(makeIrUploadRecord());
      mockedGetStrategyRuns.mockResolvedValueOnce(
        pageWithRuns([
          {
            id: "01HRUN00000000000000000001",
            status: "completed",
            started_at: "2026-04-25T11:55:00Z",
            completed_at: "2026-04-25T12:00:00Z",
            summary_metrics: {
              total_return_pct: "12.50",
              sharpe_ratio: "1.45",
              win_rate: "0.55",
              trade_count: 42,
            },
          },
          {
            id: "01HRUN00000000000000000002",
            status: "failed",
            started_at: "2026-04-24T11:55:00Z",
            completed_at: "2026-04-24T12:00:00Z",
            summary_metrics: {
              total_return_pct: null,
              sharpe_ratio: null,
              win_rate: null,
              trade_count: 0,
            },
          },
        ]),
      );

      renderPage();

      // Wait for the rows to render.
      await waitFor(() => {
        expect(screen.getByTestId("recent-run-row-01HRUN00000000000000000001")).toBeInTheDocument();
      });
      expect(screen.getByTestId("recent-run-row-01HRUN00000000000000000002")).toBeInTheDocument();

      // Status badges show the lifecycle status.
      expect(screen.getByTestId("recent-run-status-01HRUN00000000000000000001")).toHaveTextContent(
        /completed/,
      );
      expect(screen.getByTestId("recent-run-status-01HRUN00000000000000000002")).toHaveTextContent(
        /failed/,
      );

      // Summary cell shows the formatted return %; trades count is plain text.
      const completedRow = screen.getByTestId("recent-run-row-01HRUN00000000000000000001");
      expect(completedRow).toHaveTextContent(/12\.50%/);
      expect(completedRow).toHaveTextContent(/1\.45/);
      expect(completedRow).toHaveTextContent("42");

      // The failed row renders em-dashes for missing metrics so the cells
      // stay populated rather than collapsing to whitespace.
      const failedRow = screen.getByTestId("recent-run-row-01HRUN00000000000000000002");
      expect(failedRow).toHaveTextContent("—");

      // Total / page summary appears.
      expect(screen.getByTestId("strategy-recent-runs-summary")).toHaveTextContent(/2 total/);

      // No empty state when there are rows.
      expect(screen.queryByTestId("strategy-recent-runs-empty")).not.toBeInTheDocument();
    });

    it("navigates to /runs/:id/results when 'View results' is clicked", async () => {
      mockedGetStrategy.mockResolvedValueOnce(makeIrUploadRecord());
      mockedGetStrategyRuns.mockResolvedValueOnce(
        pageWithRuns([
          {
            id: "01HRUN00000000000000000001",
            status: "completed",
            started_at: "2026-04-25T11:55:00Z",
            completed_at: "2026-04-25T12:00:00Z",
            summary_metrics: {
              total_return_pct: "12.50",
              sharpe_ratio: "1.45",
              win_rate: "0.55",
              trade_count: 42,
            },
          },
        ]),
      );

      // Render with a catch-all results route so we can assert the
      // navigation actually landed on /runs/:id/results without
      // pulling in the real route tree.
      const renderResult = render(
        <MemoryRouter initialEntries={[`/strategy-studio/${STRATEGY_ID}`]}>
          <Routes>
            <Route path="/strategy-studio/:id" element={<StrategyDetail />} />
            <Route
              path="/runs/:runId/results"
              element={<div data-testid="run-results-stub" />}
            />
          </Routes>
        </MemoryRouter>,
      );

      await waitFor(() => {
        expect(
          renderResult.getByTestId("recent-run-view-01HRUN00000000000000000001"),
        ).toBeInTheDocument();
      });

      fireEvent.click(renderResult.getByTestId("recent-run-view-01HRUN00000000000000000001"));

      // Router swapped to the stub element at /runs/:runId/results.
      await waitFor(() => {
        expect(renderResult.getByTestId("run-results-stub")).toBeInTheDocument();
      });
      // The strategy detail page is no longer mounted.
      expect(renderResult.queryByTestId("strategy-detail-page")).not.toBeInTheDocument();
    });

    it("renders an inline error banner when the runs fetch fails", async () => {
      mockedGetStrategy.mockResolvedValueOnce(makeIrUploadRecord());
      mockedGetStrategyRuns.mockRejectedValueOnce(
        new GetStrategyRunsError("Backend exploded", 503),
      );

      renderPage();

      // Strategy body still loads (the recent-runs failure does not
      // block the rest of the page).
      await waitFor(() => {
        expect(screen.getByTestId("strategy-detail-page")).toBeInTheDocument();
      });

      await waitFor(() => {
        expect(screen.getByTestId("strategy-recent-runs-error")).toBeInTheDocument();
      });
      expect(screen.getByTestId("strategy-recent-runs-error")).toHaveTextContent(
        /backend exploded/i,
      );
    });
  });
});
