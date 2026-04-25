"""
Unit tests for libs.strategy_ir.dataset_resolver.InMemoryDatasetResolver.

Scope:
    Verify the in-memory dataset resolver:
        * resolves seeded entries,
        * raises DatasetNotFoundError on miss,
        * is thread-safe under concurrent register/resolve,
        * exposes introspection helpers for tests,
        * seeds every dataset_ref referenced by the five committed
          production experiment plans, so the M2.C2 route is fully
          functional out of the box without per-test seeding.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from libs.strategy_ir.dataset_resolver import (
    InMemoryDatasetResolver,
    seed_default_datasets,
)
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetNotFoundError,
    DatasetResolverInterface,
    ResolvedDataset,
)

# ---------------------------------------------------------------------------
# Production plan dataset_refs — what the seed must cover
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STRATEGY_REPO = _REPO_ROOT / "Strategy Repo"

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


def _production_dataset_refs() -> set[str]:
    """Collect every data_selection.dataset_ref from production plans."""
    refs: set[str] = set()
    for path in _PRODUCTION_PLAN_FILES:
        body = json.loads(path.read_text(encoding="utf-8"))
        refs.add(body["data_selection"]["dataset_ref"])
    return refs


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_resolver_implements_interface() -> None:
    """InMemoryDatasetResolver must satisfy DatasetResolverInterface."""
    resolver = InMemoryDatasetResolver()
    assert isinstance(resolver, DatasetResolverInterface)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_then_resolve_returns_value_object() -> None:
    """register() persists the entry; resolve() returns the value object."""
    resolver = InMemoryDatasetResolver()
    resolver.register("fx-test-dataset-v1", ["EURUSD", "GBPUSD"])

    resolved = resolver.resolve("fx-test-dataset-v1")
    assert isinstance(resolved, ResolvedDataset)
    assert resolved.dataset_ref == "fx-test-dataset-v1"
    assert resolved.dataset_id == "fx-test-dataset-v1"
    assert resolved.symbols == ["EURUSD", "GBPUSD"]


def test_register_overwrites_prior_value() -> None:
    """Re-registering a known ref must overwrite (idempotent seeding)."""
    resolver = InMemoryDatasetResolver()
    resolver.register("fx-test-dataset-v1", ["EURUSD"])
    resolver.register("fx-test-dataset-v1", ["GBPUSD"])
    resolved = resolver.resolve("fx-test-dataset-v1")
    assert resolved.symbols == ["GBPUSD"]


# ---------------------------------------------------------------------------
# Negative paths
# ---------------------------------------------------------------------------


def test_resolve_missing_raises_typed_error() -> None:
    """Unknown dataset_ref must raise DatasetNotFoundError."""
    resolver = InMemoryDatasetResolver()
    with pytest.raises(DatasetNotFoundError) as exc_info:
        resolver.resolve("does-not-exist")
    assert exc_info.value.dataset_ref == "does-not-exist"


def test_register_rejects_empty_dataset_ref() -> None:
    """Empty dataset_ref is a programmer error — fail fast."""
    resolver = InMemoryDatasetResolver()
    with pytest.raises(ValueError, match="dataset_ref"):
        resolver.register("", ["EURUSD"])


def test_register_rejects_empty_symbols() -> None:
    """Empty symbol list is a programmer error — fail fast."""
    resolver = InMemoryDatasetResolver()
    with pytest.raises(ValueError, match="symbols"):
        resolver.register("fx-test", [])


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def test_known_refs_returns_sorted_list() -> None:
    """known_refs() returns sorted dataset_ref keys."""
    resolver = InMemoryDatasetResolver()
    resolver.register("z-dataset", ["EURUSD"])
    resolver.register("a-dataset", ["GBPUSD"])
    assert resolver.known_refs() == ["a-dataset", "z-dataset"]


def test_clear_removes_all_entries() -> None:
    """clear() empties the registry."""
    resolver = InMemoryDatasetResolver()
    resolver.register("fx-test", ["EURUSD"])
    resolver.clear()
    assert resolver.known_refs() == []
    with pytest.raises(DatasetNotFoundError):
        resolver.resolve("fx-test")


# ---------------------------------------------------------------------------
# Default seeding — covers every production plan
# ---------------------------------------------------------------------------


def test_seed_default_datasets_covers_every_production_plan() -> None:
    """seed_default_datasets() must seed every production dataset_ref."""
    resolver = InMemoryDatasetResolver()
    seed_default_datasets(resolver)

    seeded = set(resolver.known_refs())
    production_refs = _production_dataset_refs()
    missing = production_refs - seeded
    assert not missing, (
        f"Default seed is missing production dataset_refs: {sorted(missing)}. "
        "Add them to _DEFAULT_DATASET_SEED in libs/strategy_ir/dataset_resolver.py."
    )


def test_seed_default_datasets_is_idempotent() -> None:
    """Calling seed twice must not double-register or raise."""
    resolver = InMemoryDatasetResolver()
    seed_default_datasets(resolver)
    first = sorted(resolver.known_refs())
    seed_default_datasets(resolver)
    second = sorted(resolver.known_refs())
    assert first == second


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_register_and_resolve_does_not_corrupt_store() -> None:
    """
    Hammer the resolver with concurrent registers and resolves; every
    resolve of a known key must succeed and every unknown key must
    raise DatasetNotFoundError without ever raising another exception
    type (which would indicate a torn dict view).
    """
    resolver = InMemoryDatasetResolver()
    resolver.register("seeded", ["EURUSD"])

    errors: list[BaseException] = []

    def register_loop() -> None:
        for i in range(200):
            try:
                resolver.register(f"dyn-{i}", ["EURUSD"])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    def resolve_loop() -> None:
        for _ in range(200):
            try:
                resolver.resolve("seeded")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [
        threading.Thread(target=register_loop),
        threading.Thread(target=register_loop),
        threading.Thread(target=resolve_loop),
        threading.Thread(target=resolve_loop),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert "seeded" in resolver.known_refs()


# ---------------------------------------------------------------------------
# Frozen value object
# ---------------------------------------------------------------------------


def test_resolved_dataset_is_frozen() -> None:
    """ResolvedDataset must be frozen — mutation raises."""
    resolver = InMemoryDatasetResolver()
    resolver.register("fx-test", ["EURUSD"])
    resolved = resolver.resolve("fx-test")
    with pytest.raises(Exception):  # pydantic ValidationError
        resolved.dataset_ref = "mutated"  # type: ignore[misc]
