/**
 * StrategyDetail — strategy-detail page rendered at ``/strategy-studio/:id``.
 *
 * Purpose:
 *   Land here after an IR import (M2.D1 ImportIrPanel navigates to
 *   ``/strategy-studio/{strategy.id}`` on a 201). Loads the strategy
 *   via ``GET /strategies/{id}`` (M2.C4) and renders one of two views
 *   keyed off the ``source`` discriminator:
 *
 *     - ``"ir_upload"``  → render :class:`IrDetailView` over the parsed
 *       IR + an "Execute backtest" button that opens
 *       :class:`RunBacktestModal` with ``strategyId`` pre-filled.
 *     - ``"draft_form"`` → render a compact info panel that surfaces
 *       the row's identity columns + the raw draft payload. The
 *       "Execute backtest" button is rendered but disabled because the
 *       modal needs a parsed IR to seed the backend route, and draft-
 *       form strategies never carry one.
 *
 * Responsibilities:
 *   - Read ``id`` from ``useParams`` and call :func:`getStrategy`.
 *   - Manage local loading / error / data state.
 *   - Render :class:`IrDetailView` or the draft fallback panel.
 *   - Render :class:`RunBacktestModal` when the operator clicks
 *     "Execute backtest" (only for IR-uploaded strategies).
 *   - Surface HTTP failures (404, 422, network) as a typed banner.
 *
 * Does NOT:
 *   - Mutate the strategy (read-only page).
 *   - Submit the backtest (the modal owns ``POST /runs/from-ir``).
 *   - Pre-load the experiment plan (M2.D3 supports the prop, but the
 *     ``strategies`` row does not yet carry the matching
 *     ``*.experiment_plan.json`` artifact reference; future tranche).
 *   - Manage auth (the route guard owns ``strategies:write`` enforcement).
 *
 * Dependencies:
 *   - :func:`useParams` from react-router-dom.
 *   - :func:`getStrategy`, :class:`GetStrategyError` from @/api/strategies.
 *   - :class:`IrDetailView` from @/components/strategy_studio/IrDetailView.
 *   - :class:`RunBacktestModal` from @/components/strategy_studio/RunBacktestModal.
 *   - :class:`LoadingState` from @/components/ui/LoadingState.
 *   - :func:`useAuth` from @/auth/useAuth (asserts authenticated session).
 *
 * Route: ``/strategy-studio/:id`` (protected by ``strategies:write`` scope
 *   via AuthGuard at the router layer — matches every other strategy
 *   GET in the M2.C4 backend, since the project does not define a
 *   distinct ``strategies:read`` scope).
 *
 * Example:
 *     // Triggered when the operator drops an IR file in ImportIrPanel:
 *     navigate(`/strategy-studio/${result.strategy.id}`);
 *     // → router renders <StrategyDetail /> at the matched route.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/useAuth";
import { LoadingState } from "@/components/ui/LoadingState";
import { IrDetailView } from "@/components/strategy_studio/IrDetailView";
import { RunBacktestModal } from "@/components/strategy_studio/RunBacktestModal";
import {
  DEFAULT_STRATEGY_RUNS_PAGE_SIZE,
  getStrategy,
  getStrategyRuns,
  GetStrategyError,
  GetStrategyRunsError,
  type RunStatus,
  type RunSummaryItem,
  type StrategyDetail as StrategyDetailRecord,
  type StrategyRunsPage,
} from "@/api/strategies";
import { cancelRun, CancelRunError } from "@/api/runs";

// ---------------------------------------------------------------------------
// Helpers — defensive, formatting-only
// ---------------------------------------------------------------------------

/**
 * Format an ISO-8601 timestamp into a short human-readable form.
 *
 * Args:
 *   iso: An ISO-8601 string from the backend (e.g. ``"2026-04-25T12:34:56Z"``).
 *
 * Returns:
 *   ``YYYY-MM-DD HH:mm`` (UTC) or the raw string when parsing fails.
 */
function formatIso(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Identity panel — id, version, source, audit columns.
 *
 * Rendered above the IR / draft body so the operator can confirm at a
 * glance which strategy they are looking at (the URL ULID alone is not
 * sufficiently human-readable).
 */
function StrategyHeader({ strategy }: { strategy: StrategyDetailRecord }) {
  const sourceLabel = strategy.source === "ir_upload" ? "Imported IR" : "Draft form";
  return (
    <div
      className="rounded-lg border border-surface-200 bg-white p-4"
      data-testid="strategy-detail-header"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900" data-testid="strategy-detail-name">
            {strategy.name}
          </h1>
          <p className="mt-1 font-mono text-xs text-surface-500">{strategy.id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-surface-200 bg-surface-50 px-2.5 py-0.5 text-xs font-medium text-surface-700">
            v{strategy.version}
          </span>
          <span
            data-testid="strategy-detail-source"
            className={
              "rounded-full border px-2.5 py-0.5 text-xs font-medium " +
              (strategy.source === "ir_upload"
                ? "border-brand-200 bg-brand-50 text-brand-800"
                : "border-surface-200 bg-surface-50 text-surface-700")
            }
          >
            {sourceLabel}
          </span>
          <span
            className={
              "rounded-full border px-2.5 py-0.5 text-xs font-medium " +
              (strategy.is_active
                ? "border-green-200 bg-green-50 text-green-800"
                : "border-surface-200 bg-surface-50 text-surface-500")
            }
          >
            {strategy.is_active ? "active" : "inactive"}
          </span>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-surface-600 md:grid-cols-4">
        <div>
          <dt className="font-medium uppercase tracking-wider text-surface-500">Created</dt>
          <dd className="mt-0.5">{formatIso(strategy.created_at)}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wider text-surface-500">Updated</dt>
          <dd className="mt-0.5">{formatIso(strategy.updated_at)}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wider text-surface-500">Created by</dt>
          <dd className="mt-0.5 font-mono">{strategy.created_by}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wider text-surface-500">Row version</dt>
          <dd className="mt-0.5">{strategy.row_version}</dd>
        </div>
      </dl>
    </div>
  );
}

/**
 * Draft fallback — rendered when ``source==="draft_form"``.
 *
 * Surfaces the raw draft payload so the operator can see what was
 * persisted, but explains why the "Execute backtest" affordance is
 * disabled for this branch (the modal needs a parsed IR).
 */
function DraftFallbackPanel({ strategy }: { strategy: StrategyDetailRecord }) {
  return (
    <section
      aria-label="Draft strategy"
      className="rounded-lg border border-surface-200 bg-white p-4"
      data-testid="strategy-detail-draft-panel"
    >
      <h2 className="mb-2 text-lg font-semibold text-surface-900">Draft strategy</h2>
      <p className="mb-3 text-sm text-surface-600">
        This strategy was created via the draft-form flow. The backtest modal requires a parsed
        Strategy IR; submit a research run for this strategy through a future compile-and-run
        pipeline rather than the IR-direct route.
      </p>
      <details>
        <summary className="cursor-pointer text-xs font-medium uppercase tracking-wider text-surface-500">
          Show stored draft payload
        </summary>
        <pre
          data-testid="strategy-detail-draft-json"
          className="mt-2 max-h-96 overflow-auto rounded border border-surface-200 bg-surface-50 p-3 text-xs text-surface-800"
        >
          {JSON.stringify(strategy.draft_fields ?? { raw: strategy.code }, null, 2)}
        </pre>
      </details>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Recent runs section
// ---------------------------------------------------------------------------

/**
 * Tailwind class fragments for the status pill, keyed by lifecycle status.
 *
 * Pulled into a constant so the table cells stay readable and the
 * full set of status values is documented in one place.
 */
const STATUS_BADGE_STYLES: Record<RunStatus, string> = {
  pending: "border-surface-200 bg-surface-50 text-surface-700",
  queued: "border-surface-200 bg-surface-50 text-surface-700",
  running: "border-blue-200 bg-blue-50 text-blue-800",
  completed: "border-green-200 bg-green-50 text-green-800",
  failed: "border-red-200 bg-red-50 text-red-700",
  cancelled: "border-surface-300 bg-surface-100 text-surface-600",
};

/**
 * Render a Decimal-as-string return percentage with two-decimal precision.
 *
 * Args:
 *   value: The wire-format decimal string (e.g. ``"12.5"``) or ``null``
 *     when the engine did not report this metric.
 *
 * Returns:
 *   A formatted string (e.g. ``"12.50%"``) or em-dash for missing values.
 */
function formatPercent(value: string | null): string {
  if (value === null) return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return `${num.toFixed(2)}%`;
}

/**
 * Render a Decimal-as-string Sharpe ratio with two-decimal precision.
 *
 * Args:
 *   value: The wire-format decimal string or ``null``.
 *
 * Returns:
 *   A formatted string (e.g. ``"1.45"``) or em-dash for missing values.
 */
function formatNumber(value: string | null): string {
  if (value === null) return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return num.toFixed(2);
}

/**
 * Recent runs section — paginated table of historical runs for the strategy.
 *
 * Renders below the IR detail view (or draft fallback) on the
 * StrategyDetail page. Calls ``GET /strategies/{id}/runs`` on mount and
 * whenever the page changes; surfaces empty / error states inline so a
 * failed history fetch never blocks the rest of the page from rendering.
 */
/**
 * Set of lifecycle statuses that the operator may cancel through the
 * Recent runs UI. Mirrors the backend behaviour matrix in
 * :meth:`ResearchRunService.cancel_run_with_abort`: PENDING / QUEUED
 * skip the executor pool, RUNNING aborts the in-flight task, terminal
 * statuses are no-ops (the backend returns 409 in that case).
 */
const CANCELLABLE_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "pending",
  "queued",
  "running",
]);

function RecentRunsSection({ strategyId }: { strategyId: string }) {
  const navigate = useNavigate();

  const [page, setPage] = useState(1);
  const [data, setData] = useState<StrategyRunsPage | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Per-run "is the cancel request in flight?" flag. Keyed by run id so
  // multiple buttons can be in different states without re-rendering
  // the whole table on every keystroke.
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  // ``confirmTargetId`` drives the confirm dialog; ``null`` means the
  // dialog is closed. We deliberately use a lightweight inline dialog
  // instead of pulling in a generic modal component to keep the
  // recent-runs section self-contained.
  const [confirmTargetId, setConfirmTargetId] = useState<string | null>(null);
  // Bumping ``refreshKey`` forces the load effect to re-run so a
  // successful cancel re-fetches the page without us having to thread
  // refetch wiring through useQuery.
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setErrorMessage(null);

    void (async () => {
      try {
        const result = await getStrategyRuns(strategyId, page, DEFAULT_STRATEGY_RUNS_PAGE_SIZE);
        if (!cancelled) setData(result);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof GetStrategyRunsError) {
          setErrorMessage(err.message);
        } else {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load recent runs.");
        }
        setData(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [strategyId, page, refreshKey]);

  const handleViewResults = useCallback(
    (runId: string) => {
      navigate(`/runs/${runId}/results`);
    },
    [navigate],
  );

  const handleConfirmCancel = useCallback(async () => {
    if (confirmTargetId === null) return;
    const runId = confirmTargetId;
    // Close the dialog immediately so the operator gets visual feedback
    // even if the network round-trip is slow; the per-row spinner picks
    // up the in-flight state.
    setConfirmTargetId(null);
    setCancellingId(runId);
    try {
      await cancelRun(runId);
      toast.success("Run cancelled.");
      // Force a re-fetch so the row reflects the new status without the
      // operator having to click Refresh.
      setRefreshKey((k) => k + 1);
    } catch (err) {
      if (err instanceof CancelRunError) {
        // 409 is the "already finished" branch; the backend's detail
        // string already names the no-op reason so we surface it
        // verbatim. 5xx and other shapes use the same path.
        toast.error(err.detail ?? err.message);
      } else if (err instanceof Error) {
        toast.error(err.message);
      } else {
        toast.error("Failed to cancel run.");
      }
    } finally {
      setCancellingId(null);
    }
  }, [confirmTargetId]);

  return (
    <>
    <section
      aria-label="Recent runs"
      className="rounded-lg border border-surface-200 bg-white p-4"
      data-testid="strategy-recent-runs"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-surface-900">Recent runs</h2>
        {data && data.total_count > 0 && (
          <p className="text-xs text-surface-500" data-testid="strategy-recent-runs-summary">
            {data.total_count} total · page {data.page} of {Math.max(1, data.total_pages)}
          </p>
        )}
      </div>

      {isLoading && (
        <div data-testid="strategy-recent-runs-loading" className="py-6">
          <LoadingState message="Loading recent runs…" />
        </div>
      )}

      {!isLoading && errorMessage && (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          data-testid="strategy-recent-runs-error"
          role="alert"
        >
          <strong>Error loading recent runs:</strong> {errorMessage}
        </div>
      )}

      {!isLoading && !errorMessage && data && data.runs.length === 0 && (
        <p
          className="rounded-md border border-dashed border-surface-200 bg-surface-50 px-3 py-4 text-center text-sm text-surface-500"
          data-testid="strategy-recent-runs-empty"
        >
          No runs have been submitted for this strategy yet. Click "Execute backtest" to start one.
        </p>
      )}

      {!isLoading && !errorMessage && data && data.runs.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-surface-200 text-sm">
              <thead className="bg-surface-50 text-xs uppercase tracking-wider text-surface-500">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    Started
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Total return
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Sharpe
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Trades
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-100">
                {data.runs.map((row: RunSummaryItem) => (
                  <tr key={row.id} data-testid={`recent-run-row-${row.id}`}>
                    <td className="px-3 py-2">
                      <span
                        data-testid={`recent-run-status-${row.id}`}
                        className={
                          "rounded-full border px-2.5 py-0.5 text-xs font-medium " +
                          STATUS_BADGE_STYLES[row.status]
                        }
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-surface-700">
                      {row.started_at ? formatIso(row.started_at) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-surface-800">
                      {formatPercent(row.summary_metrics.total_return_pct)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-surface-800">
                      {formatNumber(row.summary_metrics.sharpe_ratio)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-surface-800">
                      {row.summary_metrics.trade_count}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex items-center gap-2">
                        {CANCELLABLE_STATUSES.has(row.status) && (
                          <button
                            type="button"
                            data-testid={`recent-run-cancel-${row.id}`}
                            aria-label={`Cancel run ${row.id}`}
                            onClick={() => setConfirmTargetId(row.id)}
                            disabled={cancellingId === row.id}
                            className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {cancellingId === row.id ? "Cancelling…" : "Cancel"}
                          </button>
                        )}
                        <button
                          type="button"
                          data-testid={`recent-run-view-${row.id}`}
                          onClick={() => handleViewResults(row.id)}
                          className="inline-flex items-center rounded-md border border-brand-200 bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-800 hover:bg-brand-100"
                        >
                          View results
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.total_pages > 1 && (
            <div className="mt-3 flex items-center justify-between text-xs text-surface-600">
              <button
                type="button"
                data-testid="strategy-recent-runs-prev"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={data.page <= 1}
                className="inline-flex items-center rounded-md border border-surface-200 bg-white px-2.5 py-1 font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:bg-surface-100 disabled:text-surface-400"
              >
                Previous
              </button>
              <span>
                Page {data.page} of {Math.max(1, data.total_pages)}
              </span>
              <button
                type="button"
                data-testid="strategy-recent-runs-next"
                onClick={() => setPage((p) => p + 1)}
                disabled={data.page >= data.total_pages}
                className="inline-flex items-center rounded-md border border-surface-200 bg-white px-2.5 py-1 font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:bg-surface-100 disabled:text-surface-400"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>

    {confirmTargetId !== null && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="recent-runs-cancel-confirm-title"
        data-testid="recent-runs-cancel-confirm"
      >
        <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
          <h3
            id="recent-runs-cancel-confirm-title"
            className="text-lg font-semibold text-surface-900"
          >
            Cancel run?
          </h3>
          <p className="mt-2 text-sm text-surface-700">
            Cancel run <span className="font-mono text-xs">{confirmTargetId}</span>?
            This cannot be undone. Any in-flight backtest work will be aborted.
          </p>
          <div className="mt-4 flex items-center justify-end gap-2">
            <button
              type="button"
              data-testid="recent-runs-cancel-confirm-dismiss"
              onClick={() => setConfirmTargetId(null)}
              className="inline-flex items-center rounded-md border border-surface-200 bg-white px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50"
            >
              Keep running
            </button>
            <button
              type="button"
              data-testid="recent-runs-cancel-confirm-submit"
              onClick={() => void handleConfirmCancel()}
              className="inline-flex items-center rounded-md border border-red-200 bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
            >
              Cancel run
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

/**
 * Top-level component for the ``/strategy-studio/:id`` route.
 *
 * Loads the strategy on mount (or whenever the ``:id`` path param
 * changes) and dispatches to the IR view or the draft fallback panel
 * based on the ``source`` discriminator returned by the backend.
 *
 * Returns:
 *   A React element rendering one of: a loading state, an error
 *   banner, the IR detail view + backtest button, or the draft
 *   fallback panel.
 */
export default function StrategyDetail() {
  // useAuth is intentionally invoked so the page asserts a valid
  // session is present (matches the pattern in StrategyStudio /
  // RunResults). The route-level AuthGuard owns scope enforcement.
  useAuth();

  const { id: strategyId } = useParams<{ id: string }>();

  const [strategy, setStrategy] = useState<StrategyDetailRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    if (!strategyId) {
      setErrorMessage("No strategy id in URL.");
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setErrorMessage(null);
    setErrorStatus(null);
    setStrategy(null);

    void (async () => {
      try {
        const data = await getStrategy(strategyId);
        if (!cancelled) {
          setStrategy(data);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof GetStrategyError) {
          setErrorMessage(err.message);
          setErrorStatus(err.statusCode ?? null);
        } else {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load strategy.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [strategyId]);

  const handleOpenModal = useCallback(() => setIsModalOpen(true), []);
  const handleCloseModal = useCallback(() => setIsModalOpen(false), []);

  if (isLoading) {
    return (
      <div className="space-y-6" data-testid="strategy-detail-loading">
        <LoadingState message="Loading strategy…" />
      </div>
    );
  }

  if (errorMessage || !strategy) {
    return (
      <div className="space-y-6">
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          data-testid="strategy-detail-error"
          role="alert"
        >
          <strong>
            {errorStatus === 404
              ? "Strategy not found"
              : errorStatus === 422
                ? "Stored IR failed re-validation"
                : "Error loading strategy"}
            :
          </strong>{" "}
          {errorMessage ?? "Unknown error."}
        </div>
      </div>
    );
  }

  const isIrUpload = strategy.source === "ir_upload";
  const canExecuteBacktest = isIrUpload && strategy.parsed_ir != null;

  return (
    <div className="space-y-6" data-testid="strategy-detail-page">
      <StrategyHeader strategy={strategy} />

      <div className="flex items-center justify-end gap-3">
        <button
          type="button"
          data-testid="execute-backtest-button"
          onClick={handleOpenModal}
          disabled={!canExecuteBacktest}
          title={
            canExecuteBacktest
              ? "Submit a research run for this strategy"
              : "Backtest is only available for IR-uploaded strategies."
          }
          className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-surface-300"
        >
          Execute backtest
        </button>
      </div>

      {isIrUpload && strategy.parsed_ir ? (
        <IrDetailView ir={strategy.parsed_ir} />
      ) : (
        <DraftFallbackPanel strategy={strategy} />
      )}

      <RecentRunsSection strategyId={strategy.id} />

      {canExecuteBacktest && strategy.parsed_ir && (
        <RunBacktestModal
          open={isModalOpen}
          onClose={handleCloseModal}
          strategyId={strategy.id}
          // M2.D3 modal supports presetExperimentPlan; we do not yet
          // load the *.experiment_plan.json side-car alongside the IR
          // (no column on the strategies row tracks that artifact). A
          // future tranche can look up the matching plan and pass it
          // through here.
          presetExperimentPlan={undefined}
        />
      )}
    </div>
  );
}
