"""
Pydantic schema for the FXLab Experiment Plan artifact (M2.C2).

Purpose:
    Parse and validate every ``experiment_plan.json`` artifact in the
    ``Strategy Repo/`` so that ``POST /runs/from-ir`` can accept a
    typed, immutable representation rather than raw dict access.
    This module is the schema-only layer — no business logic, no I/O,
    no run orchestration. The route layer (M2.C2 in
    ``services/api/routes/runs.py``) is responsible for resolving the
    referenced ``dataset_ref`` via :mod:`libs.strategy_ir.dataset_resolver`
    and forwarding the parsed plan to :class:`ResearchRunService`.

Responsibilities:
    - Define the root :class:`ExperimentPlan` model and every nested
      model that appears in any production experiment plan or in the
      canonical example (``User Spec/Algo Specfication and
      Examples/experiment_plan.example.json``).
    - Enforce the project-wide strict-frozen contract: every model has
      ``model_config = ConfigDict(extra='forbid', frozen=True)`` so any
      new field lands as a loud :class:`pydantic.ValidationError` rather
      than silently being dropped.
    - Pin ``schema_version`` to ``"0.1-inferred"`` and ``artifact_type``
      to ``"experiment_plan"`` (same strictness bar as
      :class:`libs.contracts.strategy_ir.StrategyIR` per workplan M1.A1).

Does NOT:
    - Read files from disk; the parser is the route handler's job.
    - Resolve ``dataset_ref`` against a dataset registry (Track E /
      M4.E3 will provide :class:`DatasetService`; until then the
      in-memory :class:`InMemoryDatasetResolver` is used by the route).
    - Build a :class:`ResearchRunConfig`; that mapping is performed by
      :class:`ResearchRunService.submit_from_ir`.

Dependencies:
    - Pydantic v2 only.

Schema reference:
    - ``User Spec/Algo Specfication and Examples/experiment_plan.example.json``
    - The five production experiment plans under ``Strategy Repo/``:
        * ``FX_TurnOfMonth_USDSeasonality_D1.experiment_plan.json``
        * ``FX_SingleAsset_MeanReversion_H1.experiment_plan.json``
        * ``FX_TimeSeriesMomentum_Breakout_D1.experiment_plan.json``
        * ``FX_DoubleBollinger_TrendZone.experiment_plan.json``
        * ``FX_MTF_DailyTrend_H1Pullback.experiment_plan.json``

Example::

    import json
    from libs.contracts.experiment_plan import ExperimentPlan

    with open("FX_DoubleBollinger_TrendZone.experiment_plan.json") as fh:
        plan = ExperimentPlan.model_validate(json.load(fh))

    assert plan.strategy_ref.strategy_name == "FX_DoubleBollinger_TrendZone"
    assert plan.data_selection.dataset_ref.startswith("fx-")
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Reusable strict-frozen base
# ---------------------------------------------------------------------------


class _StrictFrozenModel(BaseModel):
    """
    Internal base providing the project-wide strict immutability config.

    Every experiment-plan model inherits from this so we never have to
    remember to repeat ``model_config = ConfigDict(extra='forbid',
    frozen=True)`` -- forgetting it on even one nested model would
    silently allow extra fields and mutation, defeating the schema's
    whole job. Mirrors the pattern in
    :mod:`libs.contracts.strategy_ir`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# strategy_ref
# ---------------------------------------------------------------------------


class StrategyRef(_StrictFrozenModel):
    """
    Reference to the strategy this experiment plan exercises.

    The ``strategy_name`` matches ``StrategyIR.metadata.strategy_name``
    in the matching ``strategy_ir.json`` artifact, and the version
    pin is independent of the strategy IR version because experiment
    plans evolve faster than the strategies they target.
    """

    strategy_name: str = Field(..., min_length=1, max_length=256)
    strategy_version: str = Field(..., min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# run_metadata
# ---------------------------------------------------------------------------


class RunMetadata(_StrictFrozenModel):
    """
    Bookkeeping fields for a research run instance.

    ``random_seed`` is required because every research run in FXLab
    must be byte-deterministic. ``run_purpose`` is free text: the
    canonical example uses ``"baseline_research_and_parameter_search"``
    and downstream stratification labels treat it as opaque.
    """

    run_purpose: str = Field(..., min_length=1, max_length=256)
    owner: str = Field(..., min_length=1, max_length=256)
    random_seed: int


# ---------------------------------------------------------------------------
# data_selection
# ---------------------------------------------------------------------------


class DataSelection(_StrictFrozenModel):
    """
    Dataset, spread-dataset, and calendar references for the run.

    ``dataset_ref`` is the load-bearing field: the route handler
    resolves it via :class:`DatasetResolverInterface` (M4.E3 will swap
    in the real :class:`DatasetService` adapter; until then the
    in-memory map is used). ``spread_dataset_ref`` and ``calendar_ref``
    are passed straight through to the engine config without
    resolution at this tranche.
    """

    dataset_ref: str = Field(..., min_length=1, max_length=256)
    dataset_version: str = Field(..., min_length=1, max_length=64)
    spread_dataset_ref: str = Field(..., min_length=1, max_length=256)
    calendar_ref: str = Field(..., min_length=1, max_length=256)


# ---------------------------------------------------------------------------
# cost_models
# ---------------------------------------------------------------------------


class CostModels(_StrictFrozenModel):
    """
    Pinned references for commission, slippage, and swap models.

    All three refs are opaque strings at the schema layer; the
    backtest engine resolves them against its own registries.
    """

    commission_model_ref: str = Field(..., min_length=1, max_length=256)
    slippage_model_ref: str = Field(..., min_length=1, max_length=256)
    swap_model_ref: str = Field(..., min_length=1, max_length=256)


# ---------------------------------------------------------------------------
# splits
# ---------------------------------------------------------------------------


class DateRange(_StrictFrozenModel):
    """
    A ``[start, end]`` ISO-8601 date range used by every split.

    Stored as plain strings rather than :class:`datetime.date` because
    the IR is consumed by both Python and (eventually) JS clients;
    keeping the wire shape as strings avoids timezone ambiguity. The
    engine layer is responsible for parsing.
    """

    start: str = Field(..., min_length=1, max_length=32)
    end: str = Field(..., min_length=1, max_length=32)


class Splits(_StrictFrozenModel):
    """
    Three-way temporal split: in-sample / out-of-sample / holdout.

    All three splits are required across every production plan we
    have surveyed. The engine enforces non-overlap; the schema does
    not, because compliance reporting cares about the originally
    declared boundaries even if they overlap.
    """

    in_sample: DateRange
    out_of_sample: DateRange
    holdout: DateRange


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


class WalkForwardSpec(_StrictFrozenModel):
    """
    Walk-forward validation parameters.

    Disabled when ``enabled=False``; remaining fields are still
    validated for shape so the engine config layer never has to
    check for ``None``.
    """

    enabled: bool
    train_window_months: int = Field(..., gt=0)
    test_window_months: int = Field(..., gt=0)
    step_months: int = Field(..., gt=0)


class MonteCarloSpec(_StrictFrozenModel):
    """
    Monte-Carlo validation parameters.

    ``method`` is free-text at this tranche; the engine layer maps
    known methods (e.g. ``"trade_sequence_resampling"``) to concrete
    resamplers and rejects unknown values.
    """

    enabled: bool
    iterations: int = Field(..., gt=0)
    method: str = Field(..., min_length=1, max_length=128)


class RegimeSegmentationSpec(_StrictFrozenModel):
    """
    Regime-segmentation validation parameters.

    ``dimensions`` is a free-form list of regime tags; the engine
    layer matches them against its registered regime classifiers.
    """

    enabled: bool
    dimensions: list[str] = Field(..., min_length=1)


class Validation(_StrictFrozenModel):
    """
    Aggregated validation spec covering all three sub-frameworks.

    Each sub-spec is required because every production plan provides
    all three; the engine layer honours each section's ``enabled``
    flag independently.
    """

    walk_forward: WalkForwardSpec
    monte_carlo: MonteCarloSpec
    regime_segmentation: RegimeSegmentationSpec


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------


class Ranking(_StrictFrozenModel):
    """
    Primary + secondary ranking metrics for the experiment.

    ``primary_metric`` is the single metric used for parameter-search
    selection; ``secondary_metrics`` are reported alongside but do
    not break ties.
    """

    primary_metric: str = Field(..., min_length=1, max_length=128)
    secondary_metrics: list[str] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# acceptance_thresholds
# ---------------------------------------------------------------------------


class AcceptanceThresholds(_StrictFrozenModel):
    """
    Hard acceptance thresholds used by the readiness report.

    A run that fails to clear any threshold is flagged as
    NON-PROMOTABLE. The schema enforces sensible numeric guards
    (positive trade count, non-negative drawdown) but leaves
    semantic comparison to the engine.
    """

    min_trade_count: int = Field(..., ge=0)
    min_profit_factor: float = Field(..., ge=0.0)
    max_drawdown_pct: float = Field(..., ge=0.0)
    min_out_of_sample_sharpe: float
    min_holdout_profit_factor: float = Field(..., ge=0.0)


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------


class Outputs(_StrictFrozenModel):
    """
    Required artifact list and persistence flag.

    ``required`` lists the artifacts the engine must emit (e.g.
    ``"trade_blotter"``, ``"equity_curve"``); ``persist_artifacts``
    controls whether they are written to durable storage.
    """

    required: list[str] = Field(..., min_length=1)
    persist_artifacts: bool


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class ExperimentPlan(_StrictFrozenModel):
    """
    The full experiment-plan artifact.

    Mirrors the top-level shape of every ``*.experiment_plan.json``
    file under ``Strategy Repo/``. Every field is either required or
    populates with a stable default; ``extra='forbid'`` ensures any
    drift surfaces as a :class:`pydantic.ValidationError` at parse
    time rather than silently corrupting downstream behaviour.

    Attributes:
        schema_version: Always ``"0.1-inferred"`` until a versioned
            schema replaces it.
        artifact_type: Always ``"experiment_plan"``.
        strategy_ref: Pointer to the target strategy IR.
        run_metadata: Owner, purpose, RNG seed.
        data_selection: Dataset, spread, calendar refs.
        cost_models: Commission/slippage/swap model refs.
        splits: In-sample / out-of-sample / holdout date ranges.
        validation: Walk-forward / Monte-Carlo / regime configs.
        ranking: Primary + secondary metric definitions.
        acceptance_thresholds: Hard pass/fail thresholds.
        outputs: Required artifact list + persistence flag.
        notes: Free-text annotations (always a list of strings in
            production plans; the canonical example matches).
    """

    schema_version: Literal["0.1-inferred"]
    artifact_type: Literal["experiment_plan"]
    strategy_ref: StrategyRef
    run_metadata: RunMetadata
    data_selection: DataSelection
    cost_models: CostModels
    splits: Splits
    validation: Validation
    ranking: Ranking
    acceptance_thresholds: AcceptanceThresholds
    outputs: Outputs
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "AcceptanceThresholds",
    "CostModels",
    "DataSelection",
    "DateRange",
    "ExperimentPlan",
    "MonteCarloSpec",
    "Outputs",
    "Ranking",
    "RegimeSegmentationSpec",
    "RunMetadata",
    "Splits",
    "StrategyRef",
    "Validation",
    "WalkForwardSpec",
]
