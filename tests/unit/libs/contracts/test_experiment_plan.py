"""
Unit tests for libs.contracts.experiment_plan.

Scope:
    Verify the Pydantic ExperimentPlan schema parses every committed
    production experiment_plan.json file in the repository without
    ValidationError, parses the canonical example, rejects hand-crafted
    malformed inputs, and survives a parse -> model_dump -> parse
    round-trip.

Test fixtures are the real production plans under Strategy Repo/ plus
the canonical example under User Spec/. Negative-case malformed
inputs are constructed in-process as Python dicts derived from a
known-good baseline; we never write fixture JSON files to disk.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from libs.contracts.experiment_plan import ExperimentPlan

# ---------------------------------------------------------------------------
# Fixture discovery — the 5 production plans + 1 canonical example
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STRATEGY_REPO = _REPO_ROOT / "Strategy Repo"
_USER_SPEC = _REPO_ROOT / "User Spec" / "Algo Specfication and Examples"

_PRODUCTION_PLAN_FILES: list[Path] = [
    _STRATEGY_REPO
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TurnOfMonth_USDSeasonality_D1.experiment_plan.json",
    _STRATEGY_REPO
    / "fxlab_chan_next3_strategy_pack"
    / "FX_SingleAsset_MeanReversion_H1.experiment_plan.json",
    _STRATEGY_REPO
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TimeSeriesMomentum_Breakout_D1.experiment_plan.json",
    _STRATEGY_REPO
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_DoubleBollinger_TrendZone.experiment_plan.json",
    _STRATEGY_REPO
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_MTF_DailyTrend_H1Pullback.experiment_plan.json",
]

_EXAMPLE_PLAN_FILE: Path = _USER_SPEC / "experiment_plan.example.json"


def _load_json(path: Path) -> dict:
    """Load a JSON file from disk and return its parsed dict body."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# Sanity check at collection time — if a fixture file disappears, fail
# loudly rather than silently skipping the parametrised case.
def test_fixture_files_exist() -> None:
    """Every production plan fixture and the example must exist."""
    for path in _PRODUCTION_PLAN_FILES:
        assert path.is_file(), f"missing production plan fixture: {path}"
    assert _EXAMPLE_PLAN_FILE.is_file(), f"missing canonical example: {_EXAMPLE_PLAN_FILE}"


# ---------------------------------------------------------------------------
# Positive parametrised tests — every committed plan must parse cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan_path",
    _PRODUCTION_PLAN_FILES,
    ids=lambda p: p.name,
)
def test_production_plan_parses_without_error(plan_path: Path) -> None:
    """Every committed *.experiment_plan.json must parse into ExperimentPlan."""
    body = _load_json(plan_path)
    plan = ExperimentPlan.model_validate(body)

    assert plan.schema_version == "0.1-inferred"
    assert plan.artifact_type == "experiment_plan"
    assert plan.strategy_ref.strategy_name  # non-empty
    assert plan.data_selection.dataset_ref  # non-empty
    assert plan.acceptance_thresholds.min_trade_count >= 0
    assert plan.outputs.required  # at least one required artifact


def test_canonical_example_parses_without_error() -> None:
    """The example_plan.example.json under User Spec/ must parse."""
    body = _load_json(_EXAMPLE_PLAN_FILE)
    plan = ExperimentPlan.model_validate(body)
    assert plan.strategy_ref.strategy_name == "EURUSD_15m_EMA_RSI_Pullback"
    assert plan.data_selection.dataset_ref == "fx-eurusd-15m-certified-v3"


# ---------------------------------------------------------------------------
# Round-trip — model_dump should produce a body that parses identically
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan_path",
    _PRODUCTION_PLAN_FILES,
    ids=lambda p: p.name,
)
def test_round_trip_dump_then_parse(plan_path: Path) -> None:
    """parse -> model_dump -> parse must produce an identical model."""
    body = _load_json(plan_path)
    plan = ExperimentPlan.model_validate(body)
    dumped = plan.model_dump(mode="json")
    re_parsed = ExperimentPlan.model_validate(dumped)
    assert re_parsed == plan


# ---------------------------------------------------------------------------
# Negative tests — malformed inputs must raise ValidationError
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_plan() -> dict:
    """Return a parsed copy of a production plan for mutation."""
    return copy.deepcopy(_load_json(_PRODUCTION_PLAN_FILES[0]))


def test_extra_top_level_field_is_rejected(baseline_plan: dict) -> None:
    """A typo at the top level must be loud, not silent."""
    baseline_plan["extra_unknown_field"] = "noise"
    with pytest.raises(ValidationError, match="extra_unknown_field"):
        ExperimentPlan.model_validate(baseline_plan)


def test_extra_nested_field_is_rejected(baseline_plan: dict) -> None:
    """Nested models must also forbid extras (e.g. inside data_selection)."""
    baseline_plan["data_selection"]["mystery_field"] = "noise"
    with pytest.raises(ValidationError, match="mystery_field"):
        ExperimentPlan.model_validate(baseline_plan)


def test_wrong_artifact_type_is_rejected(baseline_plan: dict) -> None:
    """artifact_type is a Literal and must match exactly."""
    baseline_plan["artifact_type"] = "strategy_ir"
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(baseline_plan)


def test_wrong_schema_version_is_rejected(baseline_plan: dict) -> None:
    """schema_version is a Literal and must match exactly."""
    baseline_plan["schema_version"] = "0.2-inferred"
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(baseline_plan)


def test_missing_required_field_is_rejected(baseline_plan: dict) -> None:
    """Removing splits.holdout must fail — every plan needs all 3 splits."""
    del baseline_plan["splits"]["holdout"]
    with pytest.raises(ValidationError, match="holdout"):
        ExperimentPlan.model_validate(baseline_plan)


def test_invalid_walk_forward_window_is_rejected(baseline_plan: dict) -> None:
    """train_window_months must be > 0."""
    baseline_plan["validation"]["walk_forward"]["train_window_months"] = 0
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(baseline_plan)


def test_negative_acceptance_threshold_is_rejected(baseline_plan: dict) -> None:
    """min_trade_count must be >= 0."""
    baseline_plan["acceptance_thresholds"]["min_trade_count"] = -1
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(baseline_plan)


def test_empty_outputs_required_is_rejected(baseline_plan: dict) -> None:
    """outputs.required must contain at least one artifact name."""
    baseline_plan["outputs"]["required"] = []
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(baseline_plan)


def test_empty_secondary_metrics_is_rejected(baseline_plan: dict) -> None:
    """ranking.secondary_metrics must contain at least one entry."""
    baseline_plan["ranking"]["secondary_metrics"] = []
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(baseline_plan)


# ---------------------------------------------------------------------------
# Frozen / strict semantics
# ---------------------------------------------------------------------------


def test_model_is_frozen(baseline_plan: dict) -> None:
    """Mutating a parsed plan must raise ValidationError."""
    plan = ExperimentPlan.model_validate(baseline_plan)
    with pytest.raises(ValidationError):
        plan.notes = ["mutated"]  # type: ignore[misc]
