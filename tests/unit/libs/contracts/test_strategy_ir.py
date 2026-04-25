"""
Unit tests for libs.contracts.strategy_ir.

Scope:
    Verify the Pydantic StrategyIR schema parses every production
    strategy_ir.json file in the repository without ValidationError,
    rejects hand-crafted malformed inputs, and survives a parse →
    model_dump → parse round-trip.

Test fixtures are the real production IR files under Strategy Repo/.
Negative-case malformed inputs are constructed in-process as Python
dicts derived from a known-good baseline; we never write fixture JSON
files to disk.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from libs.contracts.strategy_ir import StrategyIR

# ---------------------------------------------------------------------------
# Fixture discovery — the 5 production IR files
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STRATEGY_REPO = _REPO_ROOT / "Strategy Repo"

_PRODUCTION_IR_FILES: list[Path] = [
    _STRATEGY_REPO
    / "fxlab_chan_next3_strategy_pack"
    / "FX_SingleAsset_MeanReversion_H1.strategy_ir.json",
    _STRATEGY_REPO
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TimeSeriesMomentum_Breakout_D1.strategy_ir.json",
    _STRATEGY_REPO
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TurnOfMonth_USDSeasonality_D1.strategy_ir.json",
    _STRATEGY_REPO
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_DoubleBollinger_TrendZone.strategy_ir.json",
    _STRATEGY_REPO
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json",
]


def _load_json(path: Path) -> dict:
    """Load a JSON file from disk and return its parsed dict body."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# Sanity check at collection time — if a fixture file disappears, fail
# loudly rather than silently skipping the parametrised case.
def test_fixture_files_exist() -> None:
    """Every production IR fixture file must exist on disk."""
    for path in _PRODUCTION_IR_FILES:
        assert path.is_file(), f"missing fixture: {path}"


# ---------------------------------------------------------------------------
# Positive parametrised test — every production IR must parse cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ir_path", _PRODUCTION_IR_FILES, ids=lambda p: p.name)
def test_production_ir_parses_without_error(ir_path: Path) -> None:
    """Every committed strategy_ir.json file must parse into StrategyIR."""
    body = _load_json(ir_path)
    ir = StrategyIR.model_validate(body)
    assert ir.schema_version == "0.1-inferred"
    assert ir.artifact_type == "strategy_ir"
    assert ir.metadata.strategy_name  # non-empty
    assert len(ir.indicators) >= 1


# ---------------------------------------------------------------------------
# Negative tests — malformed inputs must raise ValidationError
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_ir() -> dict:
    """Return a parsed copy of the simplest production IR for mutation."""
    return _load_json(
        _STRATEGY_REPO
        / "fxlab_kathy_lien_public_strategy_pack"
        / "FX_DoubleBollinger_TrendZone.strategy_ir.json"
    )


def test_rejects_missing_required_top_level_section(baseline_ir: dict) -> None:
    """Removing a required top-level section must fail validation."""
    del baseline_ir["risk_model"]
    with pytest.raises(ValidationError):
        StrategyIR.model_validate(baseline_ir)


def test_rejects_wrong_artifact_type(baseline_ir: dict) -> None:
    """artifact_type must be exactly 'strategy_ir'."""
    baseline_ir["artifact_type"] = "not_a_strategy_ir"
    with pytest.raises(ValidationError):
        StrategyIR.model_validate(baseline_ir)


def test_rejects_unknown_indicator_type(baseline_ir: dict) -> None:
    """An indicator with a type outside the discriminated union must fail."""
    baseline_ir["indicators"].append(
        {
            "id": "garbage",
            "type": "this_indicator_does_not_exist",
            "source": "close",
            "length": 14,
            "timeframe": "4h",
        }
    )
    with pytest.raises(ValidationError):
        StrategyIR.model_validate(baseline_ir)


def test_rejects_bad_schema_version(baseline_ir: dict) -> None:
    """schema_version must be the pinned literal '0.1-inferred'."""
    baseline_ir["schema_version"] = "1.0.0"
    with pytest.raises(ValidationError):
        StrategyIR.model_validate(baseline_ir)


def test_rejects_missing_required_metadata_field(baseline_ir: dict) -> None:
    """Removing metadata.strategy_name must fail validation."""
    del baseline_ir["metadata"]["strategy_name"]
    with pytest.raises(ValidationError):
        StrategyIR.model_validate(baseline_ir)


# ---------------------------------------------------------------------------
# Round-trip — parse → model_dump → parse → equal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ir_path", _PRODUCTION_IR_FILES, ids=lambda p: p.name)
def test_round_trip_dump_then_parse_equals_original(ir_path: Path) -> None:
    """parse → model_dump(exclude_none=True) → parse yields an equal model."""
    body = _load_json(ir_path)
    parsed_once = StrategyIR.model_validate(body)
    dumped = parsed_once.model_dump(exclude_none=True)
    parsed_twice = StrategyIR.model_validate(dumped)
    assert parsed_once == parsed_twice


# ---------------------------------------------------------------------------
# Frozen / immutability sanity check
# ---------------------------------------------------------------------------


def test_strategy_ir_is_frozen(baseline_ir: dict) -> None:
    """StrategyIR.model_config sets frozen=True; mutation must fail."""
    ir = StrategyIR.model_validate(baseline_ir)
    with pytest.raises(ValidationError):
        ir.schema_version = "0.2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Discriminator coverage — a few targeted shape checks
# ---------------------------------------------------------------------------


def test_zscore_indicator_carries_mean_and_std_sources() -> None:
    """The Chan mean-reversion IR has a zscore indicator wired to bb_mid/bb_std."""
    body = _load_json(
        _STRATEGY_REPO
        / "fxlab_chan_next3_strategy_pack"
        / "FX_SingleAsset_MeanReversion_H1.strategy_ir.json"
    )
    ir = StrategyIR.model_validate(body)
    from libs.contracts.strategy_ir import ZscoreIndicator

    zscore_indicators = [ind for ind in ir.indicators if isinstance(ind, ZscoreIndicator)]
    assert len(zscore_indicators) == 1
    z = zscore_indicators[0]
    assert z.mean_source == "bb_mid"
    assert z.std_source == "bb_std"


def test_basket_template_parses_with_legs() -> None:
    """The Turn-of-Month IR uses entry_logic.basket_templates with legs."""
    body = _load_json(
        _STRATEGY_REPO
        / "fxlab_chan_next3_strategy_pack"
        / "FX_TurnOfMonth_USDSeasonality_D1.strategy_ir.json"
    )
    ir = StrategyIR.model_validate(body)
    assert ir.entry_logic.basket_templates is not None
    assert len(ir.entry_logic.basket_templates) == 1
    basket = ir.entry_logic.basket_templates[0]
    assert basket.id == "usd_short_tom_basket"
    assert len(basket.legs) == 6


def test_derived_fields_parse_when_present() -> None:
    """The MTF Daily IR carries top-level derived_fields."""
    body = _load_json(
        _STRATEGY_REPO
        / "fxlab_kathy_lien_public_strategy_pack"
        / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json"
    )
    ir = StrategyIR.model_validate(body)
    assert ir.derived_fields is not None
    assert len(ir.derived_fields) == 4
    assert {df.id for df in ir.derived_fields} == {
        "fib_38_long",
        "fib_61_long",
        "fib_38_short",
        "fib_61_short",
    }


def test_metadata_notes_accepts_both_string_and_list(baseline_ir: dict) -> None:
    """metadata.notes may be a single string or a list of strings."""
    list_form = copy.deepcopy(baseline_ir)
    list_form["metadata"]["notes"] = ["one", "two", "three"]
    parsed_list = StrategyIR.model_validate(list_form)
    assert parsed_list.metadata.notes == ["one", "two", "three"]

    string_form = copy.deepcopy(baseline_ir)
    string_form["metadata"]["notes"] = "a single string note"
    parsed_str = StrategyIR.model_validate(string_form)
    assert parsed_str.metadata.notes == "a single string note"
