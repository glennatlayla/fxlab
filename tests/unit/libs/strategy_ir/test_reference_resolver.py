"""
Unit tests for libs.strategy_ir.reference_resolver.

Scope:
    Verify that ReferenceResolver, applied to every production
    strategy_ir.json under ``Strategy Repo/``, produces a closed
    dependency graph (no dangling identifiers in any leaf condition,
    no orphan stop-indicator references) and returns a deterministic
    topological order of (indicator | derived_field) nodes.

    Negative cases assert that a hand-crafted IR carrying a missing
    identifier in a leaf condition fails fast with IRReferenceError
    and that the exception message names the offending value plus a
    location hint.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from libs.contracts.strategy_ir import StrategyIR
from libs.strategy_ir.reference_resolver import (
    IRReferenceError,
    ReferenceResolver,
    ResolvedReferences,
)

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


def _load_ir(path: Path) -> StrategyIR:
    """Load and validate a production IR file from disk."""
    with path.open(encoding="utf-8") as fh:
        body = json.load(fh)
    return StrategyIR.model_validate(body)


def _load_dict(path: Path) -> dict:
    """Load a production IR file as a raw dict (for mutation in negative tests)."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Sanity: fixture files present
# ---------------------------------------------------------------------------


def test_fixture_files_exist() -> None:
    """Every production IR fixture file must exist on disk."""
    for path in _PRODUCTION_IR_FILES:
        assert path.is_file(), f"missing fixture: {path}"


# ---------------------------------------------------------------------------
# Positive: every production IR resolves to a closed graph
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ir_path", _PRODUCTION_IR_FILES, ids=lambda p: p.name)
def test_production_ir_resolves_with_closed_graph(ir_path: Path) -> None:
    """Every production IR must resolve with no dangling references."""
    ir = _load_ir(ir_path)
    resolver = ReferenceResolver(ir)
    resolved = resolver.resolve()

    assert isinstance(resolved, ResolvedReferences)
    # Topological order is a list of node ids known to the IR.
    expected_node_ids = {ind.id for ind in ir.indicators}
    if ir.derived_fields is not None:
        expected_node_ids.update(df.id for df in ir.derived_fields)
    assert set(resolved.topological_order) == expected_node_ids


@pytest.mark.parametrize("ir_path", _PRODUCTION_IR_FILES, ids=lambda p: p.name)
def test_resolution_is_deterministic(ir_path: Path) -> None:
    """Two resolutions of the same IR must produce identical topological order."""
    ir = _load_ir(ir_path)
    first = ReferenceResolver(ir).resolve()
    second = ReferenceResolver(ir).resolve()
    assert first.topological_order == second.topological_order


def test_zscore_indicator_appears_after_its_dependencies() -> None:
    """price_zscore depends on bb_mid + bb_std; both must appear before it."""
    ir = _load_ir(
        _STRATEGY_REPO
        / "fxlab_chan_next3_strategy_pack"
        / "FX_SingleAsset_MeanReversion_H1.strategy_ir.json"
    )
    order = ReferenceResolver(ir).resolve().topological_order
    assert order.index("bb_mid") < order.index("price_zscore")
    assert order.index("bb_std") < order.index("price_zscore")


def test_derived_fields_appear_after_their_indicator_inputs() -> None:
    """fib_* derived fields depend on swing_high_h1 + swing_low_h1."""
    ir = _load_ir(
        _STRATEGY_REPO
        / "fxlab_kathy_lien_public_strategy_pack"
        / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json"
    )
    order = ReferenceResolver(ir).resolve().topological_order
    for derived in ("fib_38_long", "fib_61_long", "fib_38_short", "fib_61_short"):
        assert order.index("swing_high_h1") < order.index(derived)
        assert order.index("swing_low_h1") < order.index(derived)


# ---------------------------------------------------------------------------
# Positive: every leaf condition reference resolves to a known kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ir_path", _PRODUCTION_IR_FILES, ids=lambda p: p.name)
def test_every_resolved_reference_has_known_kind(ir_path: Path) -> None:
    """Every reference recorded by the resolver carries a known classification."""
    ir = _load_ir(ir_path)
    resolved = ReferenceResolver(ir).resolve()
    for ref in resolved.references:
        assert ref.kind in {
            "indicator",
            "derived_field",
            "price_field",
            "cross_timeframe",
            "literal",
            "previous_bar",
            "basket_synthetic",
            "expression_atom",
        }


# ---------------------------------------------------------------------------
# Negative: dangling reference fails fast with a useful error
# ---------------------------------------------------------------------------


def _baseline_ir_dict() -> dict:
    """Return a fresh deep copy of the simplest production IR for mutation."""
    return copy.deepcopy(
        _load_dict(
            _STRATEGY_REPO
            / "fxlab_kathy_lien_public_strategy_pack"
            / "FX_DoubleBollinger_TrendZone.strategy_ir.json"
        )
    )


def test_dangling_lhs_in_long_entry_raises_ir_reference_error() -> None:
    """A dangling lhs identifier must raise IRReferenceError naming the value."""
    body = _baseline_ir_dict()
    body["entry_logic"]["long"]["logic"]["conditions"][0]["lhs"] = "missing_id"
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    msg = str(excinfo.value)
    assert "missing_id" in msg
    # Location hint should point at the entry logic / long branch.
    assert "entry_logic" in msg
    assert "long" in msg


def test_dangling_rhs_string_in_short_entry_raises() -> None:
    """A string-valued rhs that refers to an unknown id must raise."""
    body = _baseline_ir_dict()
    body["entry_logic"]["short"]["logic"]["conditions"][0]["rhs"] = "no_such_indicator"
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    assert "no_such_indicator" in str(excinfo.value)


def test_dangling_filter_lhs_raises() -> None:
    """An unresolved identifier in a filter's lhs field must raise."""
    body = _baseline_ir_dict()
    body["filters"][0]["lhs"] = "ghost_indicator"
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    msg = str(excinfo.value)
    assert "ghost_indicator" in msg
    assert "filters" in msg


def test_dangling_stop_indicator_reference_raises() -> None:
    """An atr_multiple stop pointing at a non-existent atr indicator must raise."""
    body = _baseline_ir_dict()
    body["exit_logic"]["initial_stop"]["indicator"] = "atr_does_not_exist"
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    msg = str(excinfo.value)
    assert "atr_does_not_exist" in msg
    assert "exit_logic" in msg


def test_dangling_derived_field_input_raises() -> None:
    """A derived_field formula referencing an unknown id must raise."""
    body = copy.deepcopy(
        _load_dict(
            _STRATEGY_REPO
            / "fxlab_kathy_lien_public_strategy_pack"
            / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json"
        )
    )
    body["derived_fields"][0]["formula"] = "nonexistent_swing - 0.5"
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    assert "nonexistent_swing" in str(excinfo.value)


def test_zscore_indicator_with_missing_mean_source_raises() -> None:
    """A zscore indicator pointing at an unknown mean_source must raise."""
    body = copy.deepcopy(
        _load_dict(
            _STRATEGY_REPO
            / "fxlab_chan_next3_strategy_pack"
            / "FX_SingleAsset_MeanReversion_H1.strategy_ir.json"
        )
    )
    # Locate the price_zscore indicator and break its mean_source.
    for ind in body["indicators"]:
        if ind["id"] == "price_zscore":
            ind["mean_source"] = "nonexistent_mean"
            break
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    assert "nonexistent_mean" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Cycle detection — defensive but the production set has none
# ---------------------------------------------------------------------------


def test_self_referential_derived_field_raises_ir_reference_error() -> None:
    """A derived_field whose formula references its own id must be rejected."""
    body = copy.deepcopy(
        _load_dict(
            _STRATEGY_REPO
            / "fxlab_kathy_lien_public_strategy_pack"
            / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json"
        )
    )
    body["derived_fields"].append(
        {"id": "self_ref", "formula": "self_ref + 1.0"},
    )
    ir = StrategyIR.model_validate(body)

    with pytest.raises(IRReferenceError) as excinfo:
        ReferenceResolver(ir).resolve()

    assert "cycle" in str(excinfo.value).lower() or "self_ref" in str(excinfo.value)
