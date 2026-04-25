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
import { useParams } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { LoadingState } from "@/components/ui/LoadingState";
import { IrDetailView } from "@/components/strategy_studio/IrDetailView";
import { RunBacktestModal } from "@/components/strategy_studio/RunBacktestModal";
import {
  getStrategy,
  GetStrategyError,
  type StrategyDetail as StrategyDetailRecord,
} from "@/api/strategies";

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
