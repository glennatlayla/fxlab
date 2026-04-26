/**
 * Tests for the StrategyDiff page (side-by-side strategy IR diff).
 *
 * Verifies:
 *   - Both panels render when both strategies load successfully.
 *   - The empty / error state renders when the ``a`` query param is
 *     missing or malformed (ULID validation client-side).
 *   - The "Switch A↔B" button updates the URL search params.
 *   - The summary block reports accurate added / removed / changed
 *     counts derived from the structural diff helper.
 *   - Toggling "Hide unchanged" removes the unchanged-section rows
 *     from the rendered tree (default state is OFF).
 *
 * Example:
 *   npx vitest run src/pages/StrategyDiff.test.tsx
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import StrategyDiff from "./StrategyDiff";
import * as strategyDiffApi from "@/api/strategy_diff";
import * as strategiesApi from "@/api/strategies";
import type { StrategyDetail, StrategySource } from "@/api/strategies";
import type { StrategyDiffData } from "@/api/strategy_diff";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/strategy_diff", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/strategy_diff")>();
  return {
    ...original,
    fetchStrategyDiff: vi.fn(),
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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// ULIDs use Crockford's Base32 (no I, L, O, U). Mirrors the RunCompare
// test fixtures so the same client-side ULID validator accepts them.
const STRATEGY_A_ID = "01HSTRATAAAAAAAAAAAAAAAAAA";
const STRATEGY_B_ID = "01HSTRATBBBBBBBBBBBBBBBBBB";

/**
 * Build a :class:`StrategyDetail` fixture with sensible defaults that
 * tests can selectively override per-scenario.
 */
function makeStrategy(
  id: string,
  parsedIr: Record<string, unknown> | null,
  overrides: Partial<StrategyDetail> = {},
): StrategyDetail {
  const source: StrategySource = parsedIr ? "ir_upload" : "draft_form";
  return {
    id,
    name: `Strategy ${id.slice(-3)}`,
    code: parsedIr ? JSON.stringify(parsedIr) : "{}",
    version: "1.0.0",
    source,
    created_by: "01HUSER000000000000000001",
    is_active: true,
    row_version: 1,
    created_at: "2026-04-25T12:00:00Z",
    updated_at: "2026-04-25T12:00:00Z",
    archived_at: null,
    parsed_ir: parsedIr as StrategyDetail["parsed_ir"],
    draft_fields: parsedIr ? null : { foo: "bar" },
    ...overrides,
  };
}

/**
 * Build a diff payload with a tiny IR on each side. The default returns
 * structurally-identical IRs; overrides let individual tests introduce
 * the specific add / remove / change shapes they want to assert on.
 */
function makeDiffData(
  irA: Record<string, unknown>,
  irB: Record<string, unknown>,
): StrategyDiffData {
  return {
    strategyA: makeStrategy(STRATEGY_A_ID, irA),
    strategyB: makeStrategy(STRATEGY_B_ID, irB),
  };
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------

/**
 * Capture the active URL inside the rendered tree so tests can assert
 * on URL transitions (e.g. after the Switch A↔B button is clicked).
 */
function LocationSpy({ onLocation }: { onLocation: (path: string) => void }) {
  const location = useLocation();
  React.useEffect(() => {
    onLocation(`${location.pathname}${location.search}`);
  }, [location, onLocation]);
  return null;
}

function renderPage(initialPath: string, onLocation: (path: string) => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/strategies/diff"
          element={
            <>
              <StrategyDiff />
              <LocationSpy onLocation={onLocation} />
            </>
          }
        />
        <Route path="/strategies" element={<div data-testid="strategies-list-page" />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StrategyDiff page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders both panels when both strategies load successfully", async () => {
    const ir = { metadata: { strategy_name: "alpha", version: "1.0.0" } };
    vi.mocked(strategyDiffApi.fetchStrategyDiff).mockResolvedValue(makeDiffData(ir, ir));

    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=${STRATEGY_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("strategy-diff-panel-a")).toBeInTheDocument();
    });
    expect(screen.getByTestId("strategy-diff-panel-b")).toBeInTheDocument();
    // Both panels show their respective strategy IDs.
    expect(screen.getByTestId("strategy-diff-panel-a")).toHaveTextContent(STRATEGY_A_ID);
    expect(screen.getByTestId("strategy-diff-panel-b")).toHaveTextContent(STRATEGY_B_ID);
    // Verify the orchestrator was called with the URL params.
    expect(strategyDiffApi.fetchStrategyDiff).toHaveBeenCalledWith(STRATEGY_A_ID, STRATEGY_B_ID);
  });

  it("shows the 'Pick two strategies' error state when 'a' is missing", () => {
    renderPage(`/strategies/diff?b=${STRATEGY_B_ID}`);

    expect(screen.getByTestId("strategy-diff-missing-args")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-diff-missing-args")).toHaveTextContent(
      /pick two strategies/i,
    );
    // The orchestrator must NOT be invoked when args are incomplete.
    expect(strategyDiffApi.fetchStrategyDiff).not.toHaveBeenCalled();
  });

  it("shows the 'Pick two strategies' error state when 'b' is malformed", () => {
    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=not-a-ulid`);

    expect(screen.getByTestId("strategy-diff-missing-args")).toBeInTheDocument();
    expect(strategyDiffApi.fetchStrategyDiff).not.toHaveBeenCalled();
  });

  it("'Switch A↔B' updates the URL params", async () => {
    const ir = { metadata: { strategy_name: "alpha" } };
    vi.mocked(strategyDiffApi.fetchStrategyDiff).mockResolvedValue(makeDiffData(ir, ir));

    let lastPath = "";
    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=${STRATEGY_B_ID}`, (p) => {
      lastPath = p;
    });

    await waitFor(() => {
      expect(screen.getByTestId("strategy-diff-switch")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("strategy-diff-switch"));

    await waitFor(() => {
      expect(lastPath).toContain(`a=${STRATEGY_B_ID}`);
    });
    expect(lastPath).toContain(`b=${STRATEGY_A_ID}`);
  });

  it("summary block shows correct counts derived from the diff", async () => {
    // A → has indicators=[rsi_14], obsolete_field
    // B → has indicators=[rsi_21], description (added field)
    // Expected diff:
    //   /indicators/0/length: changed (14 → 21)  ← 1 changed
    //   /description: added                      ← 1 added
    //   /obsolete_field: removed                 ← 1 removed
    //   /indicators/0/id: unchanged
    //   /indicators/0/type: unchanged            ← 2 unchanged (at minimum)
    const irA = {
      indicators: [{ id: "rsi_14", type: "rsi", length: 14 }],
      obsolete_field: "gone",
    };
    const irB = {
      indicators: [{ id: "rsi_14", type: "rsi", length: 21 }],
      description: "new key",
    };
    vi.mocked(strategyDiffApi.fetchStrategyDiff).mockResolvedValue(makeDiffData(irA, irB));

    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=${STRATEGY_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("strategy-diff-summary")).toBeInTheDocument();
    });

    expect(screen.getByTestId("strategy-diff-summary-added")).toHaveTextContent("1");
    expect(screen.getByTestId("strategy-diff-summary-removed")).toHaveTextContent("1");
    expect(screen.getByTestId("strategy-diff-summary-changed")).toHaveTextContent("1");
  });

  it("'Hide unchanged' toggle collapses unchanged sections (default OFF)", async () => {
    const irA = { name: "alpha", version: "1.0.0" };
    const irB = { name: "alpha", version: "1.1.0" };
    vi.mocked(strategyDiffApi.fetchStrategyDiff).mockResolvedValue(makeDiffData(irA, irB));

    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=${STRATEGY_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("strategy-diff-tree")).toBeInTheDocument();
    });

    // Default state — show everything. The "name" leaf (unchanged)
    // appears in the rendered tree.
    expect(screen.getByTestId("strategy-diff-row-/name")).toBeInTheDocument();
    // The "version" leaf (changed) is also visible.
    expect(screen.getByTestId("strategy-diff-row-/version")).toBeInTheDocument();

    // Toggle "Hide unchanged" ON.
    const toggle = screen.getByTestId("strategy-diff-hide-unchanged-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(toggle.checked).toBe(true);
    });

    // Now the unchanged "name" row is suppressed; the changed "version"
    // row is still visible.
    expect(screen.queryByTestId("strategy-diff-row-/name")).not.toBeInTheDocument();
    expect(screen.getByTestId("strategy-diff-row-/version")).toBeInTheDocument();
  });

  it("renders a typed error banner when fetchStrategyDiff rejects with GetStrategyError", async () => {
    const notFound = new strategiesApi.GetStrategyError(`Strategy ${STRATEGY_B_ID} not found`, 404);
    vi.mocked(strategyDiffApi.fetchStrategyDiff).mockRejectedValue(notFound);

    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=${STRATEGY_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("strategy-diff-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("strategy-diff-error")).toHaveTextContent(STRATEGY_B_ID);
    expect(screen.getByTestId("strategy-diff-error")).toHaveTextContent(/not found/i);
  });

  it("renders the loading skeletons while fetchStrategyDiff is in flight", async () => {
    let resolveFn: (data: StrategyDiffData) => void = () => {};
    vi.mocked(strategyDiffApi.fetchStrategyDiff).mockImplementation(
      () =>
        new Promise<StrategyDiffData>((resolve) => {
          resolveFn = resolve;
        }),
    );

    renderPage(`/strategies/diff?a=${STRATEGY_A_ID}&b=${STRATEGY_B_ID}`);

    expect(screen.getByTestId("strategy-diff-loading")).toBeInTheDocument();

    const ir = { metadata: { strategy_name: "alpha" } };
    resolveFn(makeDiffData(ir, ir));

    await waitFor(() => {
      expect(screen.queryByTestId("strategy-diff-loading")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("strategy-diff-panel-a")).toBeInTheDocument();
  });
});
