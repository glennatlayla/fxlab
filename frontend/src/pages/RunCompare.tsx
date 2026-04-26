/**
 * RunCompare — side-by-side comparison of two completed runs.
 *
 * Purpose:
 *   Top-level page for the route ``/runs/compare?a={runIdA}&b={runIdB}``.
 *   Renders metrics tiles + per-run equity curves for both runs side by
 *   side, plus a combined overlay chart and a delta column tinted green
 *   (better) / red (worse) so operators can compare a base IR run vs. a
 *   parameter-variant run without screenshots.
 *
 * Responsibilities:
 *   - Read ``a`` and ``b`` URL search params via ``useSearchParams``.
 *   - Validate both look like ULIDs; surface a "Pick two runs" CTA if
 *     either is missing or malformed.
 *   - Fetch metrics + equity-curve for both runs in parallel via
 *     :func:`fetchRunCompare`.
 *   - Render two panel columns (header + metrics grid with B−A deltas +
 *     per-run equity-curve chart).
 *   - Render a combined overlay equity-curve chart with one line per run
 *     and a legend.
 *   - Provide a "Switch A↔B" button that swaps the URL params and a
 *     "Pick different runs" link back to ``/runs``.
 *   - Surface API errors with the offending run_id in a red banner.
 *
 * Does NOT:
 *   - Mutate run state.
 *   - Compute backtest metrics — both runs are fetched from the M2.C3
 *     sub-resource endpoints which carry the engine-emitted values.
 *   - Manage auth — :class:`AuthGuard` enforces ``exports:read`` at the
 *     route boundary.
 *
 * Dependencies:
 *   - useAuth from @/auth/useAuth (assert authenticated session).
 *   - fetchRunCompare from @/api/run_compare (parallel orchestrator).
 *   - recharts for the per-run and overlay charts (matches RunResults).
 *
 * Route: ``/runs/compare`` (protected by ``exports:read`` scope via AuthGuard).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "@/auth/useAuth";
import {
  RunResultsAuthError,
  RunResultsConflictError,
  RunResultsNotFoundError,
  RunResultsValidationError,
} from "@/api/run_results";
import { fetchRunCompare, type RunCompareData, type RunComparePanelData } from "@/api/run_compare";
import type { EquityCurveResponse, RunMetrics } from "@/types/run_results";

// ---------------------------------------------------------------------------
// ULID validation
// ---------------------------------------------------------------------------

/**
 * 26-character Crockford Base32 ULID. Mirrors the backend regex in
 * :data:`services.api.routes.runs.ULID_PATTERN` so the page rejects
 * obviously bogus URL params client-side without a 422 round-trip.
 */
const ULID_REGEX = /^[0-9A-HJKMNP-TV-Z]{26}$/i;

/**
 * Return ``true`` when ``value`` looks like a ULID.
 *
 * Args:
 *   value: Candidate string from the URL or input field.
 *
 * Returns:
 *   ``true`` iff ``value`` matches the 26-character Crockford pattern.
 *
 * Example:
 *   isUlidLike("01HRUNAAAAAAAAAAAAAAAAAAAA") === true
 *   isUlidLike("not-a-ulid") === false
 */
function isUlidLike(value: string | null | undefined): value is string {
  return typeof value === "string" && ULID_REGEX.test(value);
}

// ---------------------------------------------------------------------------
// Formatting helpers (kept local to avoid a circular dep with RunResults).
// ---------------------------------------------------------------------------

/**
 * Format a number to a fixed number of decimals; render "—" when null.
 */
function formatNumber(value: number | null | undefined, decimals: number = 2): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return value.toFixed(decimals);
}

/**
 * Format a percent value (already in percent units) with two decimals.
 */
function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

/**
 * Format a unit-fraction win rate (0..1) as a percentage string.
 */
function formatWinRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

/**
 * Format an ISO-8601 timestamp as ``YYYY-MM-DD HH:MM:SS`` (UTC).
 */
function formatTimestamp(timestamp: string | null | undefined): string {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  const iso = date.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}`;
}

/**
 * Format a signed delta number with explicit sign for display.
 *
 * Args:
 *   delta: The numeric delta (B − A).
 *   suffix: Optional suffix appended after the formatted value (e.g. "%").
 *   decimals: Number of decimals to render (default 2).
 *
 * Returns:
 *   ``"+1.23"`` / ``"-0.50"`` / ``"0.00"`` / ``"—"``.
 */
function formatDelta(
  delta: number | null | undefined,
  suffix: string = "",
  decimals: number = 2,
): string {
  if (delta === null || delta === undefined) return "—";
  if (Number.isNaN(delta)) return "—";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(decimals)}${suffix}`;
}

/**
 * Format a signed integer delta with explicit sign.
 */
function formatIntDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "—";
  if (Number.isNaN(delta)) return "—";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${Math.trunc(delta)}`;
}

// ---------------------------------------------------------------------------
// Delta direction → tint mapping
// ---------------------------------------------------------------------------

type DeltaDirection = "better" | "worse" | "neutral";

/**
 * Compute the delta direction for a metric.
 *
 * Args:
 *   delta: The signed delta (B − A).
 *   higherIsBetter: ``true`` if a positive delta means an improvement
 *     (e.g. Sharpe, return, win rate). ``false`` if a positive delta
 *     means worse (e.g. max drawdown becoming "less negative" is
 *     better → higher is better; but for raw delta on a negative value
 *     domain we still want positive=better, so this argument captures
 *     that nuance for the caller). Pass ``"informational"`` via the
 *     wrapping caller for metrics like trade count.
 *
 * Returns:
 *   "better" / "worse" / "neutral" classification.
 */
function classifyDelta(delta: number | null | undefined, higherIsBetter: boolean): DeltaDirection {
  if (delta === null || delta === undefined || Number.isNaN(delta) || delta === 0) {
    return "neutral";
  }
  if (higherIsBetter) {
    return delta > 0 ? "better" : "worse";
  }
  return delta < 0 ? "better" : "worse";
}

/**
 * Tailwind class name fragment for the delta tint.
 *
 * ``green`` and ``red`` substrings appear in the test assertions, so
 * we keep them in the class name even though Tailwind also resolves
 * the ``text-`` prefix.
 */
function deltaClass(direction: DeltaDirection): string {
  if (direction === "better") return "text-green-600 font-medium";
  if (direction === "worse") return "text-red-600 font-medium";
  return "text-surface-500";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SinglePanelProps {
  side: "A" | "B";
  data: RunComparePanelData;
  /**
   * The "other" panel's metrics, used to compute the B−A deltas displayed
   * on side B. On side A this is undefined and no delta column renders.
   */
  otherMetrics?: RunMetrics;
}

/**
 * One side of the comparison view (A or B).
 *
 * Renders:
 *   - Header (run id, status, completed_at).
 *   - Metrics grid; on side B each metric also shows the B−A delta
 *     tinted green / red according to the metric's direction-of-better.
 *   - Per-run equity-curve chart.
 */
function SinglePanel({ side, data, otherMetrics }: SinglePanelProps) {
  const { meta, metrics, equityCurve } = data;
  const showDeltas = side === "B" && otherMetrics !== undefined;

  /**
   * Compute the signed delta for a single metric. ``null`` propagates
   * when either operand is null so we render "—" instead of a misleading
   * value.
   */
  const computeDelta = (
    bValue: number | null | undefined,
    aValue: number | null | undefined,
  ): number | null => {
    if (bValue === null || bValue === undefined || Number.isNaN(bValue)) return null;
    if (aValue === null || aValue === undefined || Number.isNaN(aValue)) return null;
    return bValue - aValue;
  };

  const deltaSharpe = showDeltas
    ? computeDelta(metrics.sharpe_ratio, otherMetrics?.sharpe_ratio)
    : null;
  const deltaReturn = showDeltas
    ? computeDelta(metrics.total_return_pct, otherMetrics?.total_return_pct)
    : null;
  const deltaDrawdown = showDeltas
    ? computeDelta(metrics.max_drawdown_pct, otherMetrics?.max_drawdown_pct)
    : null;
  const deltaWinRate = showDeltas ? computeDelta(metrics.win_rate, otherMetrics?.win_rate) : null;
  const deltaProfitFactor = showDeltas
    ? computeDelta(metrics.profit_factor, otherMetrics?.profit_factor)
    : null;
  const deltaTrades = showDeltas ? metrics.total_trades - (otherMetrics?.total_trades ?? 0) : 0;

  return (
    <div
      className="flex flex-col gap-4 rounded-lg border border-surface-200 bg-white p-4 shadow-sm"
      data-testid={`run-compare-panel-${side.toLowerCase()}`}
    >
      <header className="border-b border-surface-100 pb-3">
        <p className="text-2xs font-semibold uppercase tracking-wider text-surface-400">
          Run {side}
        </p>
        <p className="mt-1 break-all font-mono text-sm text-surface-900">{meta.run_id}</p>
        <p className="mt-1 text-xs text-surface-500">
          status: <span className="font-medium text-surface-700">{meta.status}</span>
          {meta.completed_at ? (
            <span className="ml-2">· completed {formatTimestamp(meta.completed_at)}</span>
          ) : null}
        </p>
      </header>

      <section aria-label={`Run ${side} metrics`}>
        <div className="grid grid-cols-2 gap-3">
          <MetricCell
            label="Total Return"
            value={formatPercent(metrics.total_return_pct)}
            deltaText={showDeltas ? formatDelta(deltaReturn, "%") : undefined}
            deltaClassName={showDeltas ? deltaClass(classifyDelta(deltaReturn, true)) : undefined}
            deltaTestId="delta-total-return"
          />
          <MetricCell
            label="Sharpe"
            value={formatNumber(metrics.sharpe_ratio)}
            deltaText={showDeltas ? formatDelta(deltaSharpe) : undefined}
            deltaClassName={showDeltas ? deltaClass(classifyDelta(deltaSharpe, true)) : undefined}
            deltaTestId="delta-sharpe"
          />
          <MetricCell
            label="Max Drawdown"
            value={formatPercent(metrics.max_drawdown_pct)}
            // For drawdown, "more negative" is worse, so higherIsBetter=true
            // (a positive delta means the drawdown moved in the positive
            // direction, i.e. became less negative).
            deltaText={showDeltas ? formatDelta(deltaDrawdown, "%") : undefined}
            deltaClassName={showDeltas ? deltaClass(classifyDelta(deltaDrawdown, true)) : undefined}
            deltaTestId="delta-max-drawdown"
          />
          <MetricCell
            label="Win Rate"
            value={formatWinRate(metrics.win_rate)}
            deltaText={
              showDeltas
                ? formatDelta(
                    deltaWinRate !== null && deltaWinRate !== undefined ? deltaWinRate * 100 : null,
                    "%",
                  )
                : undefined
            }
            deltaClassName={showDeltas ? deltaClass(classifyDelta(deltaWinRate, true)) : undefined}
            deltaTestId="delta-win-rate"
          />
          <MetricCell
            label="Profit Factor"
            value={formatNumber(metrics.profit_factor)}
            deltaText={showDeltas ? formatDelta(deltaProfitFactor) : undefined}
            deltaClassName={
              showDeltas ? deltaClass(classifyDelta(deltaProfitFactor, true)) : undefined
            }
            deltaTestId="delta-profit-factor"
          />
          <MetricCell
            label="Trade Count"
            value={String(metrics.total_trades)}
            deltaText={showDeltas ? formatIntDelta(deltaTrades) : undefined}
            // Trade-count is informational — render the delta but don't
            // tint it green/red since "more trades" is neither inherently
            // better nor worse.
            deltaClassName={showDeltas ? deltaClass("neutral") : undefined}
            deltaTestId="delta-trade-count"
          />
        </div>
      </section>

      <section aria-label={`Run ${side} equity curve`}>
        <p className="mb-1 text-xs font-medium uppercase tracking-wider text-surface-500">
          Equity Curve
        </p>
        <PerSideEquityChart equityCurve={equityCurve} side={side} />
      </section>
    </div>
  );
}

interface MetricCellProps {
  label: string;
  value: string;
  deltaText?: string;
  deltaClassName?: string;
  deltaTestId: string;
}

/**
 * One metric in the per-side metrics grid.
 *
 * Renders the formatted value and, on side B, the B−A delta with the
 * directional tint applied. The delta cell carries a stable
 * ``data-testid`` so tests can assert on the exact rendered text and
 * class name.
 */
function MetricCell({ label, value, deltaText, deltaClassName, deltaTestId }: MetricCellProps) {
  return (
    <div className="rounded-md border border-surface-100 bg-surface-50 p-3">
      <p className="text-2xs font-medium uppercase tracking-wider text-surface-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-surface-900">{value}</p>
      {deltaText !== undefined ? (
        <p className={`mt-1 text-xs ${deltaClassName ?? ""}`} data-testid={deltaTestId}>
          Δ {deltaText}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Compact equity-curve chart shown inside a single panel (one line).
 */
function PerSideEquityChart({
  equityCurve,
  side,
}: {
  equityCurve: EquityCurveResponse;
  side: "A" | "B";
}) {
  if (equityCurve.points.length === 0) {
    return (
      <div
        className="flex h-40 items-center justify-center text-sm text-surface-400"
        data-testid={`run-compare-panel-${side.toLowerCase()}-empty`}
      >
        No equity-curve points returned for this run.
      </div>
    );
  }

  return (
    <div className="h-40" data-testid={`run-compare-panel-${side.toLowerCase()}-chart`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={equityCurve.points} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="timestamp"
            tick={{ fontSize: 10 }}
            tickFormatter={(ts: string) => ts.slice(0, 10)}
          />
          <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
          <Tooltip
            formatter={(value: number) => [
              value.toLocaleString("en-US", { minimumFractionDigits: 2 }),
              "Equity",
            ]}
            labelFormatter={(ts: string) => `Time: ${formatTimestamp(ts)}`}
          />
          <Line
            type="monotone"
            dataKey="equity"
            stroke={side === "A" ? "#2563eb" : "#dc2626"}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Combined chart overlaying both runs' equity curves on the same axes.
 *
 * The two series are joined on a per-index basis (sample 0 from A is
 * paired with sample 0 from B) for charting purposes — the exact
 * timestamp shown on the X axis is the A-side timestamp, which keeps the
 * implementation simple and is sufficient for visual side-by-side
 * comparison. Operators interested in time-aligned data should use the
 * per-side panels above.
 */
function OverlayEquityChart({ data }: { data: RunCompareData }) {
  const series = useMemo(() => {
    const aPoints = data.runA.equityCurve.points;
    const bPoints = data.runB.equityCurve.points;
    const length = Math.max(aPoints.length, bPoints.length);
    const rows: {
      index: number;
      timestamp: string;
      equityA: number | null;
      equityB: number | null;
    }[] = [];
    for (let i = 0; i < length; i++) {
      const a = aPoints[i];
      const b = bPoints[i];
      rows.push({
        index: i,
        timestamp: a?.timestamp ?? b?.timestamp ?? "",
        equityA: a ? a.equity : null,
        equityB: b ? b.equity : null,
      });
    }
    return rows;
  }, [data]);

  if (series.length === 0) {
    return (
      <div
        className="flex h-72 items-center justify-center text-sm text-surface-400"
        data-testid="run-compare-overlay-empty"
      >
        Neither run has equity-curve points to overlay.
      </div>
    );
  }

  return (
    <div className="h-72" data-testid="run-compare-overlay-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="timestamp"
            tick={{ fontSize: 12 }}
            tickFormatter={(ts: string) => (ts ? ts.slice(0, 10) : "")}
          />
          <YAxis tick={{ fontSize: 12 }} domain={["auto", "auto"]} />
          <Tooltip
            formatter={(value: number, name: string) => [
              value.toLocaleString("en-US", { minimumFractionDigits: 2 }),
              name,
            ]}
            labelFormatter={(ts: string) => `Time: ${formatTimestamp(ts)}`}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="equityA"
            name={`Run A (${data.runA.meta.run_id.slice(0, 8)}…)`}
            stroke="#2563eb"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="equityB"
            name={`Run B (${data.runB.meta.run_id.slice(0, 8)}…)`}
            stroke="#dc2626"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

/**
 * Translate any error thrown by the run-compare orchestrator into a
 * user-facing string that surfaces both run IDs (so the operator can
 * tell which side failed).
 *
 * For typed run-results errors we forward the offending ``run_id`` from
 * the message itself (the API layer already includes it). For everything
 * else we attach both IDs as a comma-separated list.
 */
function getCompareErrorMessage(err: unknown, runIdA: string, runIdB: string): string {
  if (err instanceof RunResultsNotFoundError) {
    return `${err.message} (comparing ${runIdA} vs ${runIdB}).`;
  }
  if (err instanceof RunResultsConflictError) {
    return `${err.message} (comparing ${runIdA} vs ${runIdB}).`;
  }
  if (err instanceof RunResultsAuthError) {
    return `${err.message} (comparing ${runIdA} vs ${runIdB}).`;
  }
  if (err instanceof RunResultsValidationError) {
    return `${err.message} (comparing ${runIdA} vs ${runIdB}).`;
  }
  if (err instanceof Error) {
    return `Failed to compare runs ${runIdA} and ${runIdB}: ${err.message}`;
  }
  return `Failed to compare runs ${runIdA} and ${runIdB}.`;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

/**
 * Validate the URL params; both must be present AND look like ULIDs.
 *
 * Returns:
 *   ``{ ok: true, a, b }`` when both params validate; otherwise
 *   ``{ ok: false }`` so the caller renders the empty/error state.
 */
function readUlidParams(
  search: URLSearchParams,
): { ok: true; a: string; b: string } | { ok: false; rawA: string | null; rawB: string | null } {
  const rawA = search.get("a");
  const rawB = search.get("b");
  if (isUlidLike(rawA) && isUlidLike(rawB)) {
    return { ok: true, a: rawA, b: rawB };
  }
  return { ok: false, rawA, rawB };
}

export default function RunCompare() {
  const [searchParams, setSearchParams] = useSearchParams();
  // useAuth assertion: the AuthGuard wrapper has already verified the
  // session and the exports:read scope; calling useAuth here keeps the
  // hook semantics consistent with sibling pages.
  useAuth();

  const parsed = readUlidParams(searchParams);
  const runIdA = parsed.ok ? parsed.a : null;
  const runIdB = parsed.ok ? parsed.b : null;

  const [data, setData] = useState<RunCompareData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(parsed.ok);
  const [error, setError] = useState<string | null>(null);

  // Fetch both runs in parallel whenever the (validated) URL params change.
  useEffect(() => {
    if (!runIdA || !runIdB) {
      setData(null);
      setIsLoading(false);
      setError(null);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function load(a: string, b: string) {
      setIsLoading(true);
      setError(null);
      setData(null);
      try {
        const result = await fetchRunCompare(a, b, controller.signal);
        if (cancelled) return;
        setData(result);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(getCompareErrorMessage(err, a, b));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load(runIdA, runIdB);

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runIdA, runIdB]);

  /** Swap A↔B by rewriting the URL params; the effect above re-fetches. */
  const handleSwitch = useCallback(() => {
    if (!runIdA || !runIdB) return;
    setSearchParams({ a: runIdB, b: runIdA });
  }, [runIdA, runIdB, setSearchParams]);

  // -------------------------------------------------------------------------
  // Empty / error state when the URL params aren't both valid ULIDs.
  // -------------------------------------------------------------------------
  if (!parsed.ok) {
    return (
      <div className="space-y-6 p-6" data-testid="run-compare-page">
        <header>
          <h1 className="text-2xl font-bold text-surface-900">Compare Runs</h1>
          <p className="mt-1 text-sm text-surface-500">
            Side-by-side comparison of two completed research runs.
          </p>
        </header>

        <div
          className="rounded-lg border border-amber-200 bg-amber-50 p-4"
          role="alert"
          data-testid="run-compare-missing-args"
        >
          <p className="text-sm text-amber-900">
            Pick two runs to compare. The URL must include both <code>?a=</code> and{" "}
            <code>&amp;b=</code> with valid run ULIDs.
          </p>
          <p className="mt-2 text-xs text-amber-800">
            <span className="font-medium">a:</span> <code>{parsed.rawA ?? "<missing>"}</code>{" "}
            <span className="ml-3 font-medium">b:</span> <code>{parsed.rawB ?? "<missing>"}</code>
          </p>
          <div className="mt-3">
            <Link
              to="/runs"
              className="inline-flex items-center rounded-md border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-900 hover:bg-amber-100"
              data-testid="run-compare-pick-runs"
            >
              Pick two runs →
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Happy path — both run IDs validated; render header + (loading | error |
  // panels + overlay).
  // -------------------------------------------------------------------------
  return (
    <div className="space-y-6 p-6" data-testid="run-compare-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Compare Runs</h1>
          <p className="mt-1 text-sm text-surface-500">
            Run A: <span className="font-mono">{runIdA}</span> · Run B:{" "}
            <span className="font-mono">{runIdB}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleSwitch}
            className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50"
            data-testid="run-compare-switch"
          >
            Switch A↔B
          </button>
          <Link
            to="/runs"
            className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50"
            data-testid="run-compare-pick-different"
          >
            Pick different runs
          </Link>
        </div>
      </header>

      {isLoading ? (
        <div
          className="grid grid-cols-1 gap-4 md:grid-cols-2"
          data-testid="run-compare-loading"
          aria-busy="true"
        >
          <PanelSkeleton side="A" />
          <PanelSkeleton side="B" />
        </div>
      ) : null}

      {error && !isLoading ? (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4"
          role="alert"
          data-testid="run-compare-error"
        >
          <p className="text-sm text-red-700">{error}</p>
        </div>
      ) : null}

      {!isLoading && !error && data ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2" data-testid="run-compare-panels">
            <SinglePanel side="A" data={data.runA} />
            <SinglePanel side="B" data={data.runB} otherMetrics={data.runA.metrics} />
          </div>

          <section
            aria-label="Combined equity curves"
            className="rounded-lg border border-surface-200 bg-white p-4 shadow-sm"
          >
            <h2 className="mb-3 text-lg font-semibold text-surface-900">Equity Curves (overlay)</h2>
            <OverlayEquityChart data={data} />
          </section>
        </>
      ) : null}
    </div>
  );
}

/**
 * Loading skeleton for one panel; shown twice while the parallel fetch
 * is in flight.
 */
function PanelSkeleton({ side }: { side: "A" | "B" }) {
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-surface-200 bg-white p-4"
      data-testid={`run-compare-skeleton-${side.toLowerCase()}`}
    >
      <div className="h-4 w-12 animate-pulse rounded bg-surface-200" />
      <div className="h-5 w-3/4 animate-pulse rounded bg-surface-200" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-surface-200" />
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded bg-surface-100" />
        ))}
      </div>
      <div className="h-40 animate-pulse rounded bg-surface-100" />
    </div>
  );
}
