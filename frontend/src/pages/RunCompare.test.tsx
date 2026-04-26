/**
 * Tests for the RunCompare page component (M-compare).
 *
 * Verifies:
 *   - Renders both panels (A and B) when both runs load successfully.
 *   - Shows the "Pick two runs" empty / error state when ``a`` or ``b``
 *     is missing or malformed in the URL.
 *   - Clicking the "Switch A↔B" button updates the URL search params so
 *     the previous A becomes the new B.
 *   - Metrics deltas are computed as ``B − A`` and styled green when the
 *     delta represents a "better" outcome (e.g. higher Sharpe), red when
 *     the delta is "worse".
 *   - The combined equity-curve chart renders both series.
 *
 * Example:
 *   npx vitest run src/pages/RunCompare.test.tsx
 */

import React, { type ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import RunCompare from "./RunCompare";
import * as runCompareApi from "@/api/run_compare";
import * as runResultsApi from "@/api/run_results";
import type { EquityCurveResponse, RunMetrics } from "@/types/run_results";
import type { RunCompareData } from "@/api/run_compare";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/run_compare", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/run_compare")>();
  return {
    ...original,
    fetchRunCompare: vi.fn(),
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

// Replace recharts' ResponsiveContainer with a fixed-size pass-through so
// the inner LineChart receives non-zero dimensions in JSDOM and renders
// real <path> SVG elements (mirrors RunResults.test.tsx).
vi.mock("recharts", async (importOriginal) => {
  const original = await importOriginal<typeof import("recharts")>();
  return {
    ...original,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => {
      const child = children as React.ReactElement<{ width?: number; height?: number }>;
      if (child && typeof child === "object" && "props" in child) {
        return (
          <div data-testid="responsive-container">
            {React.cloneElement(child, { width: 600, height: 300 })}
          </div>
        );
      }
      return <div data-testid="responsive-container">{children}</div>;
    },
  };
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// ULIDs use Crockford's Base32 (no I, L, O, U). Avoid those letters in
// the test fixtures so the client-side validator accepts them; the
// backend uses the same character set.
const RUN_A_ID = "01HRN0AAAAAAAAAAAAAAAAAAAA";
const RUN_B_ID = "01HRN0BBBBBBBBBBBBBBBBBBBB";

function makeMetrics(runId: string, overrides: Partial<RunMetrics> = {}): RunMetrics {
  return {
    run_id: runId,
    completed_at: "2026-04-12T12:34:56Z",
    total_return_pct: 10.0,
    annualized_return_pct: 8.0,
    max_drawdown_pct: -5.0,
    sharpe_ratio: 1.0,
    total_trades: 100,
    win_rate: 0.5,
    profit_factor: 1.5,
    final_equity: 110000.0,
    bars_processed: 5000,
    summary_metrics: {},
    ...overrides,
  };
}

function makeEquityCurve(runId: string, pointCount: number = 5): EquityCurveResponse {
  const points = Array.from({ length: pointCount }, (_, i) => ({
    timestamp: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
    equity: 100000 + i * 500,
  }));
  return {
    run_id: runId,
    point_count: points.length,
    points,
  };
}

function makeCompareData(
  metricsA: Partial<RunMetrics> = {},
  metricsB: Partial<RunMetrics> = {},
): RunCompareData {
  const mA = makeMetrics(RUN_A_ID, metricsA);
  const mB = makeMetrics(RUN_B_ID, metricsB);
  return {
    runA: {
      meta: { run_id: RUN_A_ID, status: "completed", completed_at: mA.completed_at },
      metrics: mA,
      equityCurve: makeEquityCurve(RUN_A_ID, 5),
    },
    runB: {
      meta: { run_id: RUN_B_ID, status: "completed", completed_at: mB.completed_at },
      metrics: mB,
      equityCurve: makeEquityCurve(RUN_B_ID, 5),
    },
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
          path="/runs/compare"
          element={
            <>
              <RunCompare />
              <LocationSpy onLocation={onLocation} />
            </>
          }
        />
        <Route path="/runs" element={<div data-testid="runs-list-page" />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RunCompare page (M-compare)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders both panels when both runs load successfully", async () => {
    vi.mocked(runCompareApi.fetchRunCompare).mockResolvedValue(makeCompareData());

    renderPage(`/runs/compare?a=${RUN_A_ID}&b=${RUN_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("run-compare-panel-a")).toBeInTheDocument();
    });

    expect(screen.getByTestId("run-compare-panel-a")).toBeInTheDocument();
    expect(screen.getByTestId("run-compare-panel-b")).toBeInTheDocument();
    // Both panels show their respective run IDs in the header.
    expect(screen.getByTestId("run-compare-panel-a")).toHaveTextContent(RUN_A_ID);
    expect(screen.getByTestId("run-compare-panel-b")).toHaveTextContent(RUN_B_ID);
    // Combined equity-curve chart is rendered with both series.
    expect(screen.getByTestId("run-compare-overlay-chart")).toBeInTheDocument();
    // Verify the orchestrator was called with the URL params.
    expect(runCompareApi.fetchRunCompare).toHaveBeenCalledWith(
      RUN_A_ID,
      RUN_B_ID,
      expect.anything(),
    );
  });

  it("shows the 'Pick two runs' error state when 'a' is missing", async () => {
    renderPage(`/runs/compare?b=${RUN_B_ID}`);

    expect(screen.getByTestId("run-compare-missing-args")).toBeInTheDocument();
    expect(screen.getByTestId("run-compare-missing-args")).toHaveTextContent(/pick two runs/i);
    // The orchestrator must NOT be invoked when args are incomplete.
    expect(runCompareApi.fetchRunCompare).not.toHaveBeenCalled();
  });

  it("shows the 'Pick two runs' error state when 'b' is malformed (not a ULID)", async () => {
    renderPage(`/runs/compare?a=${RUN_A_ID}&b=not-a-ulid`);

    expect(screen.getByTestId("run-compare-missing-args")).toBeInTheDocument();
    expect(runCompareApi.fetchRunCompare).not.toHaveBeenCalled();
  });

  it("'Switch A↔B' updates the URL params (A becomes B and vice versa)", async () => {
    vi.mocked(runCompareApi.fetchRunCompare).mockResolvedValue(makeCompareData());

    let lastPath = "";
    renderPage(`/runs/compare?a=${RUN_A_ID}&b=${RUN_B_ID}`, (p) => {
      lastPath = p;
    });

    await waitFor(() => {
      expect(screen.getByTestId("run-compare-switch")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-compare-switch"));

    await waitFor(() => {
      expect(lastPath).toContain(`a=${RUN_B_ID}`);
    });
    expect(lastPath).toContain(`b=${RUN_A_ID}`);
  });

  it("renders metrics deltas with the correct sign and style (B − A)", async () => {
    // A: Sharpe=1.0, MaxDD=-5.0, Return=10.0, Trades=100
    // B: Sharpe=1.4, MaxDD=-7.0, Return=12.5, Trades=120
    // Deltas (B-A): Sharpe=+0.40 (better → green); MaxDD=-2.00 (worse,
    //   more negative drawdown → red); Return=+2.50 (better → green);
    //   Trades=+20 (neutral, no styling).
    vi.mocked(runCompareApi.fetchRunCompare).mockResolvedValue(
      makeCompareData(
        { sharpe_ratio: 1.0, max_drawdown_pct: -5.0, total_return_pct: 10.0, total_trades: 100 },
        { sharpe_ratio: 1.4, max_drawdown_pct: -7.0, total_return_pct: 12.5, total_trades: 120 },
      ),
    );

    renderPage(`/runs/compare?a=${RUN_A_ID}&b=${RUN_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("delta-sharpe")).toBeInTheDocument();
    });

    const sharpeDelta = screen.getByTestId("delta-sharpe");
    expect(sharpeDelta).toHaveTextContent("+0.40");
    expect(sharpeDelta.className).toMatch(/green/);

    const ddDelta = screen.getByTestId("delta-max-drawdown");
    // -7.0 - (-5.0) = -2.00 (more negative drawdown → worse).
    expect(ddDelta).toHaveTextContent("-2.00%");
    expect(ddDelta.className).toMatch(/red/);

    const retDelta = screen.getByTestId("delta-total-return");
    expect(retDelta).toHaveTextContent("+2.50%");
    expect(retDelta.className).toMatch(/green/);

    const tradesDelta = screen.getByTestId("delta-trade-count");
    // Trade count is informational — render the delta but don't tint.
    expect(tradesDelta).toHaveTextContent("+20");
  });

  it("surfaces an error banner with the offending run id when fetchRunCompare rejects", async () => {
    const notFound = new runResultsApi.RunResultsNotFoundError(RUN_B_ID);
    vi.mocked(runCompareApi.fetchRunCompare).mockRejectedValue(notFound);

    renderPage(`/runs/compare?a=${RUN_A_ID}&b=${RUN_B_ID}`);

    await waitFor(() => {
      expect(screen.getByTestId("run-compare-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("run-compare-error")).toHaveTextContent(RUN_B_ID);
    expect(screen.getByTestId("run-compare-error")).toHaveTextContent(/not found/i);
  });

  it("renders the loading skeletons while fetchRunCompare is in flight", async () => {
    let resolveFn: (data: RunCompareData) => void = () => {};
    vi.mocked(runCompareApi.fetchRunCompare).mockImplementation(
      () =>
        new Promise<RunCompareData>((resolve) => {
          resolveFn = resolve;
        }),
    );

    renderPage(`/runs/compare?a=${RUN_A_ID}&b=${RUN_B_ID}`);

    expect(screen.getByTestId("run-compare-loading")).toBeInTheDocument();

    resolveFn(makeCompareData());

    await waitFor(() => {
      expect(screen.queryByTestId("run-compare-loading")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("run-compare-panel-a")).toBeInTheDocument();
  });
});
