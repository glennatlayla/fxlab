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
import { GetStrategyError, type StrategyDetail as StrategyDetailRecord } from "@/api/strategies";
import type { StrategyIR } from "@/types/strategy_ir";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/strategies", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/strategies")>();
  return {
    ...original,
    getStrategy: vi.fn(),
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

// Pull the mocked getStrategy reference for per-test arrangement.
import * as strategiesApi from "@/api/strategies";
const mockedGetStrategy = strategiesApi.getStrategy as unknown as ReturnType<typeof vi.fn>;

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
});
