/**
 * RunBacktestModal — "Execute backtest" modal for the strategy detail page.
 *
 * Purpose:
 *   Open a modal that lets the operator either review an experiment plan
 *   uploaded alongside the StrategyIR (``presetExperimentPlan``) or
 *   hand-edit a fresh plan field-by-field. On submit, POST the plan to
 *   ``/runs/from-ir`` (M2.C2) and navigate to the run monitor with the
 *   newly created ``run_id`` pinned in the URL.
 *
 * Responsibilities:
 *   - Render every field of :class:`ExperimentPlan` (mirror of
 *     ``libs/contracts/experiment_plan.py``) so the user can edit a
 *     plan from scratch when nothing was uploaded.
 *   - Run :func:`validateExperimentPlan` on every change to expose
 *     inline field errors (positive integers, ISO dates, etc.).
 *   - Disable the submit button while there are validation errors or
 *     while a submission is in flight.
 *   - Submit via :func:`submitRunFromIr` and, on 201, call
 *     ``onClose()`` and navigate to ``/runs/{run_id}``.
 *   - Translate 404 / 422 / 500 backend responses into a single
 *     dismissible error banner inside the modal, plus per-field
 *     errors when the backend returns Pydantic ``loc`` paths.
 *   - Honour focus trap, escape-to-close, body scroll lock (mirrors
 *     ``ConfirmationModal`` so the studio's UX is consistent).
 *
 * Does NOT:
 *   - Fetch the strategy or its uploaded plan; the parent page passes
 *     ``presetExperimentPlan`` when one was uploaded with the IR.
 *   - Poll run status (the run monitor at ``/runs/:runId`` does that).
 *   - Resolve dataset references (the backend route does that and
 *     returns 404 if the ref is unknown).
 *
 * Navigation target on 201:
 *   ``/runs/{run_id}`` — the run monitor with the new run pinned via
 *   the path parameter. The route name aligns with the existing
 *   ``/runs/:runId/readiness`` route (which already uses the ULID in
 *   the path). M2.D4 owns RunResults and may add a deeper
 *   ``/runs/:runId/results`` route; navigating to ``/runs/{run_id}``
 *   keeps both options open without coupling this tranche to a route
 *   that does not exist yet.
 *
 * Dependencies:
 *   - React (useState, useEffect, useMemo, useRef, useCallback).
 *   - react-router-dom (useNavigate).
 *   - @/api/runs (submitRunFromIr).
 *   - @/types/experiment_plan (types + validator + factory).
 *
 * Auth scope: ``runs:write`` (enforced by the backend route; the
 * modal is rendered only on pages already gated by that scope).
 *
 * Example:
 *   <RunBacktestModal
 *     open={isOpen}
 *     onClose={() => setOpen(false)}
 *     strategyId="01HZ0000000000000000000001"
 *     presetExperimentPlan={uploadedPlan}
 *   />
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { submitRunFromIr } from "@/api/runs";
import { buildEmptyExperimentPlan, validateExperimentPlan } from "@/types/experiment_plan";
import type { ExperimentPlan, ExperimentPlanErrors } from "@/types/experiment_plan";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface RunBacktestModalProps {
  /** Whether the modal is mounted/visible. Parent owns this state. */
  open: boolean;
  /** Called when the user closes the modal (cancel, escape, backdrop, success). */
  onClose: () => void;
  /** ULID of the strategy this run will execute. Required by the backend. */
  strategyId: string;
  /** Optional plan uploaded alongside the IR; pre-fills every field when present. */
  presetExperimentPlan?: ExperimentPlan;
}

// ---------------------------------------------------------------------------
// Focus trap (mirrors ConfirmationModal — kept inline so this component
// stays self-contained for the M2.D3 tranche; we can extract a shared
// BaseModal later without changing the public API of RunBacktestModal).
// ---------------------------------------------------------------------------

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

// ---------------------------------------------------------------------------
// Helpers — shape-preserving immutable updates against the deeply nested
// ExperimentPlan. Each helper is narrow on purpose; broader helpers risk
// silently dropping fields when the plan grows.
// ---------------------------------------------------------------------------

type SectionUpdater<K extends keyof ExperimentPlan> = (patch: Partial<ExperimentPlan[K]>) => void;

/**
 * Map a backend Pydantic 422 body's ``detail`` list onto our flat
 * ``ExperimentPlanErrors`` keyed by dotted path.
 *
 * FastAPI returns ``detail`` as a list of ``{loc, msg, type}`` items
 * where ``loc`` starts with ``["body", "experiment_plan", ...]``. We
 * strip the request-shape prefix so the resulting keys line up with
 * :func:`validateExperimentPlan`'s output.
 *
 * Args:
 *   detail: Either the full FastAPI 422 detail array, a string, or
 *     ``undefined`` when the response was not a structured 422.
 *
 * Returns:
 *   ``{ fieldErrors, formError }`` — ``formError`` is set when we
 *   could not extract any field-level errors so the user still sees
 *   something explanatory at the top of the modal.
 */
function parseBackendErrors(detail: unknown): {
  fieldErrors: ExperimentPlanErrors;
  formError: string | null;
} {
  if (typeof detail === "string") {
    return { fieldErrors: {}, formError: detail };
  }
  if (!Array.isArray(detail)) {
    return { fieldErrors: {}, formError: null };
  }

  const fieldErrors: ExperimentPlanErrors = {};
  let formError: string | null = null;

  for (const item of detail) {
    if (typeof item !== "object" || item === null) continue;
    const rec = item as { loc?: unknown; msg?: unknown };
    if (typeof rec.msg !== "string") continue;

    if (Array.isArray(rec.loc)) {
      const segments = rec.loc.filter(
        (s): s is string | number => typeof s === "string" || typeof s === "number",
      );
      // Drop the leading "body" / "experiment_plan" segments so the path
      // matches our client-side dotted keys.
      const trimmed = segments.filter((s) => s !== "body" && s !== "experiment_plan");
      if (trimmed.length > 0) {
        const path = trimmed.join(".");
        fieldErrors[path] = rec.msg;
        continue;
      }
    }
    // Fallback — couldn't pin the error to a field.
    formError = formError ? `${formError}; ${rec.msg}` : rec.msg;
  }

  return { fieldErrors, formError };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RunBacktestModal({
  open,
  onClose,
  strategyId,
  presetExperimentPlan,
}: RunBacktestModalProps): ReactElement | null {
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // ---- State ----
  const [plan, setPlan] = useState<ExperimentPlan>(
    () => presetExperimentPlan ?? buildEmptyExperimentPlan(),
  );
  const [submitting, setSubmitting] = useState(false);
  const [serverFieldErrors, setServerFieldErrors] = useState<ExperimentPlanErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  // Reset the plan when the parent swaps out the preset (e.g. the user
  // imports a new IR + plan pair without unmounting the modal).
  useEffect(() => {
    if (open) {
      setPlan(presetExperimentPlan ?? buildEmptyExperimentPlan());
      setServerFieldErrors({});
      setFormError(null);
    }
  }, [open, presetExperimentPlan]);

  // ---- Validation ----
  const clientErrors = useMemo(() => validateExperimentPlan(plan), [plan]);
  const errors = useMemo<ExperimentPlanErrors>(
    () => ({ ...clientErrors, ...serverFieldErrors }),
    [clientErrors, serverFieldErrors],
  );
  const isValid = Object.keys(clientErrors).length === 0;

  // ---- Section updaters ----
  const updateSection = useCallback(<K extends keyof ExperimentPlan>(key: K): SectionUpdater<K> => {
    return (patch) => {
      setPlan((prev) => ({
        ...prev,
        [key]: { ...(prev[key] as object), ...patch } as ExperimentPlan[K],
      }));
    };
  }, []);

  const updateStrategyRef = updateSection("strategy_ref");
  const updateRunMetadata = updateSection("run_metadata");
  const updateDataSelection = updateSection("data_selection");
  const updateCostModels = updateSection("cost_models");
  const updateAcceptance = updateSection("acceptance_thresholds");

  const updateSplit = useCallback(
    (which: keyof ExperimentPlan["splits"], patch: Partial<{ start: string; end: string }>) => {
      setPlan((prev) => ({
        ...prev,
        splits: {
          ...prev.splits,
          [which]: { ...prev.splits[which], ...patch },
        },
      }));
    },
    [],
  );

  const updateWalkForward = useCallback(
    (patch: Partial<ExperimentPlan["validation"]["walk_forward"]>) => {
      setPlan((prev) => ({
        ...prev,
        validation: {
          ...prev.validation,
          walk_forward: { ...prev.validation.walk_forward, ...patch },
        },
      }));
    },
    [],
  );

  const updateMonteCarlo = useCallback(
    (patch: Partial<ExperimentPlan["validation"]["monte_carlo"]>) => {
      setPlan((prev) => ({
        ...prev,
        validation: {
          ...prev.validation,
          monte_carlo: { ...prev.validation.monte_carlo, ...patch },
        },
      }));
    },
    [],
  );

  const updateRegime = useCallback(
    (patch: Partial<ExperimentPlan["validation"]["regime_segmentation"]>) => {
      setPlan((prev) => ({
        ...prev,
        validation: {
          ...prev.validation,
          regime_segmentation: { ...prev.validation.regime_segmentation, ...patch },
        },
      }));
    },
    [],
  );

  const updateRanking = useCallback((patch: Partial<ExperimentPlan["ranking"]>) => {
    setPlan((prev) => ({ ...prev, ranking: { ...prev.ranking, ...patch } }));
  }, []);

  const updateOutputs = useCallback((patch: Partial<ExperimentPlan["outputs"]>) => {
    setPlan((prev) => ({ ...prev, outputs: { ...prev.outputs, ...patch } }));
  }, []);

  // ---- Focus trap, scroll lock, escape ----
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (!submitting) onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR);
        if (focusable.length === 0) return;
        const first = focusable[0] as HTMLElement;
        const last = focusable[focusable.length - 1] as HTMLElement;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onClose, submitting],
  );

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = setTimeout(() => {
      const first = dialogRef.current?.querySelector(FOCUSABLE_SELECTOR) as HTMLElement | null;
      first?.focus();
    }, 0);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      clearTimeout(timer);
      document.body.style.overflow = originalOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [open, handleKeyDown]);

  // ---- Submit ----
  const handleSubmit = useCallback(async () => {
    if (!isValid || submitting) return;
    setSubmitting(true);
    setServerFieldErrors({});
    setFormError(null);

    try {
      const { run_id } = await submitRunFromIr(strategyId, plan);
      onClose();
      navigate(`/runs/${run_id}`);
    } catch (err: unknown) {
      // Translate the backend response into inline + banner errors.
      if (axios.isAxiosError(err) && err.response) {
        const status = err.response.status;
        const detail = (err.response.data as { detail?: unknown })?.detail;
        if (status === 422) {
          const { fieldErrors, formError: fe } = parseBackendErrors(detail);
          setServerFieldErrors(fieldErrors);
          setFormError(fe ?? "The experiment plan was rejected by the backend.");
        } else if (status === 404) {
          setFormError(
            typeof detail === "string"
              ? detail
              : "Dataset reference not found. Check data_selection.dataset_ref.",
          );
        } else {
          setFormError(
            typeof detail === "string" ? detail : `Backend rejected the run (status ${status}).`,
          );
        }
      } else {
        setFormError(err instanceof Error ? err.message : "Network error submitting backtest.");
      }
      setSubmitting(false);
    }
  }, [isValid, submitting, strategyId, plan, navigate, onClose]);

  if (!open) return null;

  // ---- Render helpers ----
  const fieldError = (path: string): string | undefined => errors[path];

  const textInput = (
    id: string,
    label: string,
    path: string,
    value: string,
    onChange: (e: ChangeEvent<HTMLInputElement>) => void,
  ): ReactElement => (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-surface-700">
        {label}
      </label>
      <input
        id={id}
        data-testid={`field-${path}`}
        type="text"
        value={value}
        onChange={onChange}
        className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
      />
      {fieldError(path) && (
        <p data-testid={`error-${path}`} className="mt-1 text-xs text-red-600">
          {fieldError(path)}
        </p>
      )}
    </div>
  );

  const numberInput = (
    id: string,
    label: string,
    path: string,
    value: number,
    onChange: (n: number) => void,
    opts?: { step?: number; min?: number },
  ): ReactElement => (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-surface-700">
        {label}
      </label>
      <input
        id={id}
        data-testid={`field-${path}`}
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={opts?.step ?? 1}
        min={opts?.min}
        onChange={(e) => {
          const parsed = Number(e.target.value);
          onChange(Number.isFinite(parsed) ? parsed : 0);
        }}
        className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
      />
      {fieldError(path) && (
        <p data-testid={`error-${path}`} className="mt-1 text-xs text-red-600">
          {fieldError(path)}
        </p>
      )}
    </div>
  );

  const dateInput = (
    id: string,
    label: string,
    path: string,
    value: string,
    onChange: (s: string) => void,
  ): ReactElement => (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-surface-700">
        {label}
      </label>
      <input
        id={id}
        data-testid={`field-${path}`}
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
      />
      {fieldError(path) && (
        <p data-testid={`error-${path}`} className="mt-1 text-xs text-red-600">
          {fieldError(path)}
        </p>
      )}
    </div>
  );

  return (
    <div
      data-testid="run-backtest-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        data-testid="run-backtest-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Execute backtest"
        className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-surface-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Execute backtest</h2>
            <p className="mt-1 text-xs text-surface-500">
              Submit a research run from the experiment plan.
              {presetExperimentPlan
                ? " Plan loaded from upload — edit before submit if needed."
                : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded p-1 text-surface-500 hover:bg-surface-100 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-4">
          {formError && (
            <div
              data-testid="form-error"
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              role="alert"
            >
              {formError}
            </div>
          )}

          {/* strategy_ref */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Strategy reference</legend>
            <div className="grid grid-cols-2 gap-3">
              {textInput(
                "rb-strategy-name",
                "Strategy name",
                "strategy_ref.strategy_name",
                plan.strategy_ref.strategy_name,
                (e) => updateStrategyRef({ strategy_name: e.target.value }),
              )}
              {textInput(
                "rb-strategy-version",
                "Strategy version",
                "strategy_ref.strategy_version",
                plan.strategy_ref.strategy_version,
                (e) => updateStrategyRef({ strategy_version: e.target.value }),
              )}
            </div>
          </fieldset>

          {/* run_metadata */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Run metadata</legend>
            <div className="grid grid-cols-2 gap-3">
              {textInput(
                "rb-run-purpose",
                "Run purpose",
                "run_metadata.run_purpose",
                plan.run_metadata.run_purpose,
                (e) => updateRunMetadata({ run_purpose: e.target.value }),
              )}
              {textInput(
                "rb-run-owner",
                "Owner",
                "run_metadata.owner",
                plan.run_metadata.owner,
                (e) => updateRunMetadata({ owner: e.target.value }),
              )}
            </div>
            {numberInput(
              "rb-random-seed",
              "Random seed (deterministic replay)",
              "run_metadata.random_seed",
              plan.run_metadata.random_seed,
              (n) => updateRunMetadata({ random_seed: Math.trunc(n) }),
            )}
          </fieldset>

          {/* data_selection */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Data selection</legend>
            <div className="grid grid-cols-2 gap-3">
              {textInput(
                "rb-dataset-ref",
                "Dataset ref",
                "data_selection.dataset_ref",
                plan.data_selection.dataset_ref,
                (e) => updateDataSelection({ dataset_ref: e.target.value }),
              )}
              {textInput(
                "rb-dataset-version",
                "Dataset version",
                "data_selection.dataset_version",
                plan.data_selection.dataset_version,
                (e) => updateDataSelection({ dataset_version: e.target.value }),
              )}
              {textInput(
                "rb-spread-ref",
                "Spread dataset ref",
                "data_selection.spread_dataset_ref",
                plan.data_selection.spread_dataset_ref,
                (e) => updateDataSelection({ spread_dataset_ref: e.target.value }),
              )}
              {textInput(
                "rb-calendar-ref",
                "Calendar ref",
                "data_selection.calendar_ref",
                plan.data_selection.calendar_ref,
                (e) => updateDataSelection({ calendar_ref: e.target.value }),
              )}
            </div>
          </fieldset>

          {/* cost_models */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Cost models</legend>
            <div className="grid grid-cols-3 gap-3">
              {textInput(
                "rb-commission",
                "Commission model ref",
                "cost_models.commission_model_ref",
                plan.cost_models.commission_model_ref,
                (e) => updateCostModels({ commission_model_ref: e.target.value }),
              )}
              {textInput(
                "rb-slippage",
                "Slippage model ref",
                "cost_models.slippage_model_ref",
                plan.cost_models.slippage_model_ref,
                (e) => updateCostModels({ slippage_model_ref: e.target.value }),
              )}
              {textInput(
                "rb-swap",
                "Swap model ref",
                "cost_models.swap_model_ref",
                plan.cost_models.swap_model_ref,
                (e) => updateCostModels({ swap_model_ref: e.target.value }),
              )}
            </div>
          </fieldset>

          {/* splits */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Splits (date ranges)</legend>
            {(["in_sample", "out_of_sample", "holdout"] as const).map((which) => (
              <div key={which} className="grid grid-cols-2 gap-3">
                {dateInput(
                  `rb-split-${which}-start`,
                  `${which.replace(/_/g, " ")} start`,
                  `splits.${which}.start`,
                  plan.splits[which].start,
                  (s) => updateSplit(which, { start: s }),
                )}
                {dateInput(
                  `rb-split-${which}-end`,
                  `${which.replace(/_/g, " ")} end`,
                  `splits.${which}.end`,
                  plan.splits[which].end,
                  (s) => updateSplit(which, { end: s }),
                )}
              </div>
            ))}
          </fieldset>

          {/* validation.walk_forward */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">
              Walk-forward validation
            </legend>
            <label className="flex items-center gap-2 text-sm text-surface-700">
              <input
                type="checkbox"
                data-testid="field-validation.walk_forward.enabled"
                checked={plan.validation.walk_forward.enabled}
                onChange={(e) => updateWalkForward({ enabled: e.target.checked })}
              />
              Walk-forward enabled
            </label>
            <div className="grid grid-cols-3 gap-3">
              {numberInput(
                "rb-wf-train",
                "Train window months",
                "validation.walk_forward.train_window_months",
                plan.validation.walk_forward.train_window_months,
                (n) => updateWalkForward({ train_window_months: Math.trunc(n) }),
                { min: 1 },
              )}
              {numberInput(
                "rb-wf-test",
                "Test window months",
                "validation.walk_forward.test_window_months",
                plan.validation.walk_forward.test_window_months,
                (n) => updateWalkForward({ test_window_months: Math.trunc(n) }),
                { min: 1 },
              )}
              {numberInput(
                "rb-wf-step",
                "Step months",
                "validation.walk_forward.step_months",
                plan.validation.walk_forward.step_months,
                (n) => updateWalkForward({ step_months: Math.trunc(n) }),
                { min: 1 },
              )}
            </div>
          </fieldset>

          {/* validation.monte_carlo */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Monte-Carlo validation</legend>
            <label className="flex items-center gap-2 text-sm text-surface-700">
              <input
                type="checkbox"
                data-testid="field-validation.monte_carlo.enabled"
                checked={plan.validation.monte_carlo.enabled}
                onChange={(e) => updateMonteCarlo({ enabled: e.target.checked })}
              />
              Monte-Carlo enabled
            </label>
            <div className="grid grid-cols-2 gap-3">
              {numberInput(
                "rb-mc-iter",
                "Iterations",
                "validation.monte_carlo.iterations",
                plan.validation.monte_carlo.iterations,
                (n) => updateMonteCarlo({ iterations: Math.trunc(n) }),
                { min: 1 },
              )}
              {textInput(
                "rb-mc-method",
                "Method",
                "validation.monte_carlo.method",
                plan.validation.monte_carlo.method,
                (e) => updateMonteCarlo({ method: e.target.value }),
              )}
            </div>
          </fieldset>

          {/* validation.regime_segmentation */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Regime segmentation</legend>
            <label className="flex items-center gap-2 text-sm text-surface-700">
              <input
                type="checkbox"
                data-testid="field-validation.regime_segmentation.enabled"
                checked={plan.validation.regime_segmentation.enabled}
                onChange={(e) => updateRegime({ enabled: e.target.checked })}
              />
              Regime segmentation enabled
            </label>
            <div>
              <label
                htmlFor="rb-regime-dims"
                className="mb-1 block text-sm font-medium text-surface-700"
              >
                Dimensions (comma-separated)
              </label>
              <input
                id="rb-regime-dims"
                data-testid="field-validation.regime_segmentation.dimensions"
                type="text"
                value={plan.validation.regime_segmentation.dimensions.join(", ")}
                onChange={(e) =>
                  updateRegime({
                    dimensions: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter((s) => s.length > 0),
                  })
                }
                className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              {fieldError("validation.regime_segmentation.dimensions") && (
                <p
                  data-testid="error-validation.regime_segmentation.dimensions"
                  className="mt-1 text-xs text-red-600"
                >
                  {fieldError("validation.regime_segmentation.dimensions")}
                </p>
              )}
            </div>
          </fieldset>

          {/* ranking */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Ranking</legend>
            {textInput(
              "rb-primary-metric",
              "Primary metric",
              "ranking.primary_metric",
              plan.ranking.primary_metric,
              (e) => updateRanking({ primary_metric: e.target.value }),
            )}
            <div>
              <label
                htmlFor="rb-secondary-metrics"
                className="mb-1 block text-sm font-medium text-surface-700"
              >
                Secondary metrics (comma-separated)
              </label>
              <input
                id="rb-secondary-metrics"
                data-testid="field-ranking.secondary_metrics"
                type="text"
                value={plan.ranking.secondary_metrics.join(", ")}
                onChange={(e) =>
                  updateRanking({
                    secondary_metrics: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter((s) => s.length > 0),
                  })
                }
                className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              {fieldError("ranking.secondary_metrics") && (
                <p
                  data-testid="error-ranking.secondary_metrics"
                  className="mt-1 text-xs text-red-600"
                >
                  {fieldError("ranking.secondary_metrics")}
                </p>
              )}
            </div>
          </fieldset>

          {/* acceptance_thresholds */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Acceptance thresholds</legend>
            <div className="grid grid-cols-2 gap-3">
              {numberInput(
                "rb-min-trades",
                "Min trade count",
                "acceptance_thresholds.min_trade_count",
                plan.acceptance_thresholds.min_trade_count,
                (n) => updateAcceptance({ min_trade_count: Math.trunc(n) }),
                { min: 0 },
              )}
              {numberInput(
                "rb-min-pf",
                "Min profit factor",
                "acceptance_thresholds.min_profit_factor",
                plan.acceptance_thresholds.min_profit_factor,
                (n) => updateAcceptance({ min_profit_factor: n }),
                { step: 0.01, min: 0 },
              )}
              {numberInput(
                "rb-max-dd",
                "Max drawdown %",
                "acceptance_thresholds.max_drawdown_pct",
                plan.acceptance_thresholds.max_drawdown_pct,
                (n) => updateAcceptance({ max_drawdown_pct: n }),
                { step: 0.1, min: 0 },
              )}
              {numberInput(
                "rb-min-oos-sharpe",
                "Min out-of-sample Sharpe",
                "acceptance_thresholds.min_out_of_sample_sharpe",
                plan.acceptance_thresholds.min_out_of_sample_sharpe,
                (n) => updateAcceptance({ min_out_of_sample_sharpe: n }),
                { step: 0.01 },
              )}
              {numberInput(
                "rb-min-holdout-pf",
                "Min holdout profit factor",
                "acceptance_thresholds.min_holdout_profit_factor",
                plan.acceptance_thresholds.min_holdout_profit_factor,
                (n) => updateAcceptance({ min_holdout_profit_factor: n }),
                { step: 0.01, min: 0 },
              )}
            </div>
          </fieldset>

          {/* outputs */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-slate-800">Outputs</legend>
            <div>
              <label
                htmlFor="rb-required-artifacts"
                className="mb-1 block text-sm font-medium text-surface-700"
              >
                Required artifacts (comma-separated)
              </label>
              <input
                id="rb-required-artifacts"
                data-testid="field-outputs.required"
                type="text"
                value={plan.outputs.required.join(", ")}
                onChange={(e) =>
                  updateOutputs({
                    required: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter((s) => s.length > 0),
                  })
                }
                className="w-full rounded-md border border-surface-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              {fieldError("outputs.required") && (
                <p data-testid="error-outputs.required" className="mt-1 text-xs text-red-600">
                  {fieldError("outputs.required")}
                </p>
              )}
            </div>
            <label className="flex items-center gap-2 text-sm text-surface-700">
              <input
                type="checkbox"
                data-testid="field-outputs.persist_artifacts"
                checked={plan.outputs.persist_artifacts}
                onChange={(e) => updateOutputs({ persist_artifacts: e.target.checked })}
              />
              Persist artifacts to durable storage
            </label>
          </fieldset>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-surface-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-surface-300 bg-white px-4 py-2 text-sm font-medium text-surface-700 hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="run-backtest-submit"
            onClick={handleSubmit}
            disabled={!isValid || submitting}
            className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-surface-300"
          >
            {submitting ? "Submitting…" : "Execute backtest"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default RunBacktestModal;
