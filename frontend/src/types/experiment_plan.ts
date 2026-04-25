/**
 * ExperimentPlan TypeScript types.
 *
 * Purpose:
 *   Mirror of ``libs/contracts/experiment_plan.py`` (M2.C2). Every nested
 *   model in the Pydantic schema has a matching ``interface`` here so the
 *   ``RunBacktestModal`` and the ``api/runs.ts`` client can build a
 *   wire-compatible payload for ``POST /runs/from-ir`` without round-tripping
 *   through ``unknown``.
 *
 * Responsibilities:
 *   - Export structural types matching the Pydantic ExperimentPlan exactly.
 *   - Provide a lightweight runtime validator (``validateExperimentPlan``)
 *     that mirrors the Pydantic invariants the modal can surface inline
 *     (required strings non-empty, positive integers, etc.). The backend is
 *     still the authoritative validator (it owns Pydantic) — this is a
 *     fast-feedback gate so users do not have to wait for a 422 round trip
 *     to learn that ``train_window_months`` must be > 0.
 *   - Provide a ``buildEmptyExperimentPlan()`` factory that returns a
 *     plan skeleton with all required fields set to safe placeholder
 *     values so the form can bind ``value=`` inputs without juggling
 *     ``undefined``.
 *
 * Does NOT:
 *   - Make API calls (see ``api/runs.ts``).
 *   - Resolve dataset references (the backend route does that).
 *   - Implement the full Pydantic strict-frozen guarantee — TypeScript
 *     interfaces cannot reject extra fields at runtime; the backend will
 *     return 422 for unknown fields.
 *
 * Schema reference:
 *   - libs/contracts/experiment_plan.py (M2.C2)
 *   - Strategy Repo/**\/*.experiment_plan.json
 */

// ---------------------------------------------------------------------------
// Nested types (one per Pydantic model in libs/contracts/experiment_plan.py)
// ---------------------------------------------------------------------------

export interface StrategyRef {
  strategy_name: string;
  strategy_version: string;
}

export interface RunMetadata {
  run_purpose: string;
  owner: string;
  random_seed: number;
}

export interface DataSelection {
  dataset_ref: string;
  dataset_version: string;
  spread_dataset_ref: string;
  calendar_ref: string;
}

export interface CostModels {
  commission_model_ref: string;
  slippage_model_ref: string;
  swap_model_ref: string;
}

export interface DateRange {
  start: string;
  end: string;
}

export interface Splits {
  in_sample: DateRange;
  out_of_sample: DateRange;
  holdout: DateRange;
}

export interface WalkForwardSpec {
  enabled: boolean;
  train_window_months: number;
  test_window_months: number;
  step_months: number;
}

export interface MonteCarloSpec {
  enabled: boolean;
  iterations: number;
  method: string;
}

export interface RegimeSegmentationSpec {
  enabled: boolean;
  dimensions: string[];
}

export interface Validation {
  walk_forward: WalkForwardSpec;
  monte_carlo: MonteCarloSpec;
  regime_segmentation: RegimeSegmentationSpec;
}

export interface Ranking {
  primary_metric: string;
  secondary_metrics: string[];
}

export interface AcceptanceThresholds {
  min_trade_count: number;
  min_profit_factor: number;
  max_drawdown_pct: number;
  min_out_of_sample_sharpe: number;
  min_holdout_profit_factor: number;
}

export interface Outputs {
  required: string[];
  persist_artifacts: boolean;
}

export interface ExperimentPlan {
  schema_version: "0.1-inferred";
  artifact_type: "experiment_plan";
  strategy_ref: StrategyRef;
  run_metadata: RunMetadata;
  data_selection: DataSelection;
  cost_models: CostModels;
  splits: Splits;
  validation: Validation;
  ranking: Ranking;
  acceptance_thresholds: AcceptanceThresholds;
  outputs: Outputs;
  notes: string[];
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/**
 * Field-level validation errors, keyed by dotted path matching the
 * Pydantic field path. The modal renders the message inline next to the
 * matching input so the user can correct one field at a time.
 *
 * Example keys:
 *   - "strategy_ref.strategy_name"
 *   - "splits.in_sample.start"
 *   - "validation.walk_forward.train_window_months"
 */
export type ExperimentPlanErrors = Record<string, string>;

/** ISO-8601 date check: ``YYYY-MM-DD`` only — calendar dates, no time. */
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Validate a hand-edited :class:`ExperimentPlan` against the same shape
 * the backend Pydantic validator enforces.
 *
 * Mirrors the most important invariants from
 * ``libs/contracts/experiment_plan.py``:
 *   - Required strings are non-empty.
 *   - All ``*_window_months`` / ``step_months`` / ``iterations`` > 0.
 *   - ``acceptance_thresholds`` numerics that have ``ge=0`` constraints.
 *   - ``splits`` dates parse as ISO-8601 ``YYYY-MM-DD``.
 *   - At least one item in lists declared with ``min_length=1``.
 *
 * Args:
 *   plan: The plan candidate from the modal form state.
 *
 * Returns:
 *   A flat error map. Empty object means the plan passes the
 *   client-side gate (the backend will still validate).
 */
export function validateExperimentPlan(plan: ExperimentPlan): ExperimentPlanErrors {
  const errors: ExperimentPlanErrors = {};

  const requireString = (path: string, value: string): void => {
    if (!value || value.trim() === "") {
      errors[path] = "Required";
    }
  };

  const requirePositiveInt = (path: string, value: number): void => {
    if (!Number.isInteger(value) || value <= 0) {
      errors[path] = "Must be a positive integer";
    }
  };

  const requireNonNegative = (path: string, value: number): void => {
    if (!Number.isFinite(value) || value < 0) {
      errors[path] = "Must be zero or greater";
    }
  };

  const requireDate = (path: string, value: string): void => {
    if (!ISO_DATE_RE.test(value)) {
      errors[path] = "Must be YYYY-MM-DD";
    }
  };

  // strategy_ref
  requireString("strategy_ref.strategy_name", plan.strategy_ref.strategy_name);
  requireString("strategy_ref.strategy_version", plan.strategy_ref.strategy_version);

  // run_metadata
  requireString("run_metadata.run_purpose", plan.run_metadata.run_purpose);
  requireString("run_metadata.owner", plan.run_metadata.owner);
  if (!Number.isInteger(plan.run_metadata.random_seed)) {
    errors["run_metadata.random_seed"] = "Must be an integer";
  }

  // data_selection
  requireString("data_selection.dataset_ref", plan.data_selection.dataset_ref);
  requireString("data_selection.dataset_version", plan.data_selection.dataset_version);
  requireString("data_selection.spread_dataset_ref", plan.data_selection.spread_dataset_ref);
  requireString("data_selection.calendar_ref", plan.data_selection.calendar_ref);

  // cost_models
  requireString("cost_models.commission_model_ref", plan.cost_models.commission_model_ref);
  requireString("cost_models.slippage_model_ref", plan.cost_models.slippage_model_ref);
  requireString("cost_models.swap_model_ref", plan.cost_models.swap_model_ref);

  // splits
  requireDate("splits.in_sample.start", plan.splits.in_sample.start);
  requireDate("splits.in_sample.end", plan.splits.in_sample.end);
  requireDate("splits.out_of_sample.start", plan.splits.out_of_sample.start);
  requireDate("splits.out_of_sample.end", plan.splits.out_of_sample.end);
  requireDate("splits.holdout.start", plan.splits.holdout.start);
  requireDate("splits.holdout.end", plan.splits.holdout.end);

  // validation.walk_forward — when enabled, all windows must be > 0.
  // The backend uses ``gt=0`` regardless of the enabled flag, so we
  // mirror that strictly to avoid a 422 surprise.
  requirePositiveInt(
    "validation.walk_forward.train_window_months",
    plan.validation.walk_forward.train_window_months,
  );
  requirePositiveInt(
    "validation.walk_forward.test_window_months",
    plan.validation.walk_forward.test_window_months,
  );
  requirePositiveInt(
    "validation.walk_forward.step_months",
    plan.validation.walk_forward.step_months,
  );

  // validation.monte_carlo
  requirePositiveInt("validation.monte_carlo.iterations", plan.validation.monte_carlo.iterations);
  requireString("validation.monte_carlo.method", plan.validation.monte_carlo.method);

  // validation.regime_segmentation — at least one dimension required.
  if (plan.validation.regime_segmentation.dimensions.length === 0) {
    errors["validation.regime_segmentation.dimensions"] = "At least one dimension required";
  }

  // ranking
  requireString("ranking.primary_metric", plan.ranking.primary_metric);
  if (plan.ranking.secondary_metrics.length === 0) {
    errors["ranking.secondary_metrics"] = "At least one secondary metric required";
  }

  // acceptance_thresholds — ge=0 on most, free sign on min_out_of_sample_sharpe.
  requireNonNegative(
    "acceptance_thresholds.min_trade_count",
    plan.acceptance_thresholds.min_trade_count,
  );
  if (
    !Number.isInteger(plan.acceptance_thresholds.min_trade_count) ||
    plan.acceptance_thresholds.min_trade_count < 0
  ) {
    errors["acceptance_thresholds.min_trade_count"] = "Must be a non-negative integer";
  }
  requireNonNegative(
    "acceptance_thresholds.min_profit_factor",
    plan.acceptance_thresholds.min_profit_factor,
  );
  requireNonNegative(
    "acceptance_thresholds.max_drawdown_pct",
    plan.acceptance_thresholds.max_drawdown_pct,
  );
  if (!Number.isFinite(plan.acceptance_thresholds.min_out_of_sample_sharpe)) {
    errors["acceptance_thresholds.min_out_of_sample_sharpe"] = "Must be a number";
  }
  requireNonNegative(
    "acceptance_thresholds.min_holdout_profit_factor",
    plan.acceptance_thresholds.min_holdout_profit_factor,
  );

  // outputs — at least one required artifact.
  if (plan.outputs.required.length === 0) {
    errors["outputs.required"] = "At least one required artifact";
  }

  return errors;
}

// ---------------------------------------------------------------------------
// Empty / preset factory
// ---------------------------------------------------------------------------

/**
 * Build an empty :class:`ExperimentPlan` with shape-correct defaults.
 *
 * The form binds ``value=`` directly against this object; using empty
 * strings (rather than ``undefined``) keeps the inputs controlled and
 * lets the modal mount without flicker. The validator will reject the
 * empty plan until the user fills it in.
 */
export function buildEmptyExperimentPlan(): ExperimentPlan {
  return {
    schema_version: "0.1-inferred",
    artifact_type: "experiment_plan",
    strategy_ref: { strategy_name: "", strategy_version: "" },
    run_metadata: { run_purpose: "", owner: "", random_seed: 0 },
    data_selection: {
      dataset_ref: "",
      dataset_version: "",
      spread_dataset_ref: "",
      calendar_ref: "",
    },
    cost_models: {
      commission_model_ref: "",
      slippage_model_ref: "",
      swap_model_ref: "",
    },
    splits: {
      in_sample: { start: "", end: "" },
      out_of_sample: { start: "", end: "" },
      holdout: { start: "", end: "" },
    },
    validation: {
      walk_forward: {
        enabled: false,
        train_window_months: 12,
        test_window_months: 3,
        step_months: 1,
      },
      monte_carlo: { enabled: false, iterations: 100, method: "trade_sequence_resampling" },
      regime_segmentation: { enabled: false, dimensions: [] },
    },
    ranking: { primary_metric: "", secondary_metrics: [] },
    acceptance_thresholds: {
      min_trade_count: 0,
      min_profit_factor: 0,
      max_drawdown_pct: 0,
      min_out_of_sample_sharpe: 0,
      min_holdout_profit_factor: 0,
    },
    outputs: { required: [], persist_artifacts: true },
    notes: [],
  };
}
