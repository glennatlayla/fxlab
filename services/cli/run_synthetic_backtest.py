"""
End-to-end CLI: run a single Strategy IR through a synthetic FX backtest (M3.X1).

Purpose:
    Provide a deterministic, fully-reproducible path from a parsed
    ``strategy_ir.json`` to a JSON trade blotter without any network,
    real broker, or wall-clock dependency. This is the M3.X1
    integration gate per
    ``docs/workplan/2026-04-25-strategy-execution-agent-orchestration.md``,
    executed against synthetic data so it does not block on operator-
    supplied Oanda fxpractice credentials (those land with M4.E2 /
    M4.E5).

    As of M2.D3 the heavy orchestration (IR sanitisation, compile,
    bar replay, signal-to-order translation, trade pairing, equity
    sampling, metrics) lives in
    :class:`services.api.services.synthetic_backtest_executor.SyntheticBacktestExecutor`.
    This module is a thin CLI wrapper around the executor: argparse +
    JSON blotter writer + summary printer. The shared helpers below
    (``_IRPreprocessor``, ``_IRIndicatorComputer``, ``_TradePairer``,
    ``_TradeRecord``, ``_resolve_symbols``, ``_resolve_timeframe``,
    ``_position_snapshot``, ``_signal_to_order_side``,
    ``_PAPER_ORDER_UNITS``, ``SyntheticBacktestError``) are imported
    by the executor so CLI and API share one orchestration codepath.

Pipeline (one bar at a time, in chronological order):
    1.  Parse the IR via :class:`libs.contracts.strategy_ir.StrategyIR`.
    2.  Sanitise the IR for the compiler's runtime requirements (see
        :class:`_IRPreprocessor` -- filters the IR's
        ``same_bar_priority`` list down to entries that actually
        correspond to configured exit stops; the compiler now natively
        supports ``spread`` and cross-timeframe price-field
        identifiers, so neither is stripped).
    3.  Resolve references via
        :class:`libs.strategy_ir.reference_resolver.ReferenceResolver`
        (raises :class:`IRReferenceError` on dangling identifiers).
    4.  Compile to an :class:`libs.strategy_ir.compiler.IRStrategy` and
        replay every bar through a
        :class:`libs.strategy_ir.paper_broker_adapter.PaperBrokerAdapter`
        + :class:`libs.strategy_ir.synthetic_market_data_provider.SyntheticFxMarketDataProvider`.

Determinism contract:
    Same ``--ir`` file + same ``--start`` / ``--end`` window + same
    ``--seed`` => byte-identical ``--output`` blotter on every run.
    The CLI itself never reads a wall clock, never calls a random
    number generator, and never touches the network.

Responsibilities:
    - Argparse: ``--ir``, ``--start``, ``--end``, ``--seed``,
      ``--output``, ``--symbols`` (optional override), ``--timeframe``
      (optional override of the IR's primary timeframe), ``--starting-balance``.
    - Delegate orchestration to
      :class:`SyntheticBacktestExecutor` and serialise its output.
    - Print summary metrics (total trades, win rate, total return %,
      Sharpe ratio) to stdout.

Does NOT:
    - Modify any sibling-tranche file (the synthetic provider, the
      paper broker, or anything outside this module).
    - Touch the network, an external broker, or any database.
    - Persist the run beyond the ``--output`` JSON file.
    - Provide a Python public API beyond :func:`main` -- this module
      is invoked exclusively via ``python -m services.cli.run_synthetic_backtest``.

Dependencies (all imported, none injected):
    - :mod:`services.api.services.synthetic_backtest_executor`
      (M2.D3 reusable orchestrator).
    - :mod:`libs.contracts.strategy_ir`
    - :mod:`libs.contracts.market_data`
    - :mod:`libs.contracts.execution`
    - :mod:`libs.strategy_ir.compiler`
    - :mod:`libs.strategy_ir.clock`
    - :mod:`libs.strategy_ir.synthetic_market_data_provider`
    - :mod:`libs.strategy_ir.paper_broker_adapter`
    - :mod:`libs.strategy_ir.interfaces.broker_adapter_interface`
    - :mod:`libs.indicators` (for the default ``IndicatorEngine``)

Raises:
    - :class:`SyntheticBacktestError`: any expected error path
      (missing IR file, invalid window, IR fails to compile, no
      candles produced, etc.). Caught at :func:`main` and translated
      to a non-zero exit code with a clear stderr message.

Example:
    .venv/bin/python -m services.cli.run_synthetic_backtest \\
        --ir 'Strategy Repo/.../FX_DoubleBollinger_TrendZone.strategy_ir.json' \\
        --start 2026-01-01 --end 2026-04-01 --seed 42 \\
        --output /tmp/blotter.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from libs.contracts.execution import PositionSnapshot
from libs.contracts.indicator import IndicatorResult
from libs.contracts.market_data import Candle
from libs.contracts.signal import SignalDirection, SignalType
from libs.contracts.strategy_ir import (
    AdxIndicator,
    AtrIndicator,
    BollingerLowerIndicator,
    BollingerUpperIndicator,
    CalendarBusinessDayIndexIndicator,
    CalendarDaysToMonthEndIndicator,
    EmaIndicator,
    Indicator,
    RollingHighIndicator,
    RollingLowIndicator,
    RollingMaxIndicator,
    RollingMinIndicator,
    RollingStddevIndicator,
    RsiIndicator,
    SmaIndicator,
    StrategyIR,
    ZscoreIndicator,
)
from libs.indicators import default_engine
from libs.strategy_ir.interfaces.broker_adapter_interface import (
    OrderSide,
)
from libs.strategy_ir.paper_broker_adapter import (
    FillEvent,
    PaperBrokerAdapter,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The seven major FX pairs the synthetic provider knows about.
#: Symbols outside this set are skipped (with a warning to stderr)
#: rather than failing the run -- many production IRs declare a wider
#: universe than the synthetic provider models, and refusing them
#: would block every M3.X1 smoke test.
_SYNTHETIC_SUPPORTED_SYMBOLS: frozenset[str] = frozenset(
    {
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
    }
)

#: IR ``data_requirements.primary_timeframe`` strings mapped to the
#: strings the synthetic provider's ``fetch_bars`` accepts. The provider
#: itself accepts both upper-case (``"H1"``) and lower-case (``"1h"``)
#: forms; we normalise via this table so the CLI can also accept
#: legacy strings (``"4h"``) the IR pack uses.
_TIMEFRAME_NORMALISATION: dict[str, str] = {
    "M15": "M15",
    "15m": "M15",
    "H1": "H1",
    "1h": "H1",
    "H4": "H4",
    "4h": "H4",
    "D": "D",
    "D1": "D",
    "1d": "D",
}

#: Fixed unit size for every paper order. The CLI is the M3.X1 smoke
#: test, not a tuned production runner: a single uniform unit size
#: keeps the blotter assertions deterministic and decoupled from the
#: M1.A5 risk translator (which is exercised separately by its own
#: unit tests). Production sizing flows through the compiled
#: ``risk_model`` once the M3.X2 viable-candidate path lands.
_PAPER_ORDER_UNITS: int = 10_000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SyntheticBacktestError(Exception):
    """
    Raised by :func:`main` (or its helpers) when the run cannot
    proceed. Always carries an operator-readable message naming the
    offending input. The CLI catches this in :func:`main` and exits
    with status 2 after writing the message to stderr.
    """


# ---------------------------------------------------------------------------
# IR pre-processing -- compiler-capability gap accommodation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _IRPreprocessReport:
    """
    Diagnostic record describing what the pre-processor changed.

    Fields:
        dropped_conditions: human-readable list of leaf conditions
            removed because their LHS or RHS referenced an identifier
            outside :attr:`_IRPreprocessor._UNSUPPORTED_PRICE_FIELDS`.
            Currently always empty -- the compiler natively supports
            every price-field reference the production IRs use
            (``spread`` and cross-timeframe ``close_1d`` style
            identifiers); the field is retained so a future capability
            gap (e.g., a not-yet-supported derived field) can plug in
            without changing the report's shape.
        dropped_required_fields: names removed from
            ``data_requirements.required_fields`` because they are not
            modelled by the synthetic candle stream.
        dropped_priority_entries: names removed from
            ``exit_logic.same_bar_priority`` because they reference
            stops that are not configured in this IR.

    Why exposed as a dataclass:
        The CLI prints the report to stderr so operators can audit
        exactly what was sanitised. Two consecutive runs against the
        same IR therefore produce the same diagnostic output.
    """

    dropped_conditions: tuple[str, ...]
    dropped_required_fields: tuple[str, ...]
    dropped_priority_entries: tuple[str, ...]


class _IRPreprocessor:
    """
    Sanitise a raw IR dict for the M1.A3 compiler's runtime requirements.

    Why this exists:
        The Strategy Repo IRs commonly list ``same_bar_priority``
        entries (e.g. ``"trailing_stop"``, ``"time_exit"``) for stops
        the IR does not actually configure. The compiler resolves
        :attr:`exit_logic.same_bar_priority` strictly and would reject
        such IRs at compile time. This sanitiser drops the dangling
        priority entries, leaving the rest of the IR intact, and
        records every drop in an :class:`_IRPreprocessReport` so the
        change is auditable.

        Cross-timeframe identifiers (e.g. ``close_1d``) and the
        ``spread`` price field were both previously stripped here as
        compiler-capability workarounds. The compiler now reads both
        natively (cross-tf via per-(symbol, timeframe) bucket
        aggregation; spread via :attr:`Candle.spread` with pip
        conversion), so the sanitiser no longer touches entry-side
        leaves -- it only filters the priority list.

    Why this is NOT a stub:
        The remaining behaviour (priority filtering) is exact: the
        compiler's "what counts as a configured stop" rules are
        mirrored here in :attr:`_PRIORITY_NAME_ALIASES` so the
        sanitiser never silently disables a stop the compiler would
        accept.

    Does NOT:
        - Mutate exit-logic conditions or entry-side leaves. The
          compiler accepts every identifier the resolver classifies.
        - Add or fabricate any condition. The sanitiser only drops.
        - Persist anything; the report is in-memory.
    """

    #: Identifier names whose presence on either side of a leaf
    #: condition would trigger a drop. Currently empty: every price
    #: field the production IRs reference (open/high/low/close/volume,
    #: spread, and the cross-timeframe ``close_1d``-style suffixes)
    #: is supported by the compiler. Retained as a frozenset so a
    #: future capability gap can be plugged in without changing the
    #: leaf-walk shape.
    _UNSUPPORTED_PRICE_FIELDS: frozenset[str] = frozenset()

    #: Aliases mirrored from
    #: :attr:`libs.strategy_ir.compiler.StrategyIRCompiler._PRIORITY_NAME_ALIASES`.
    #: A priority entry whose name is in this map is considered
    #: configured when the canonical target is configured. Kept here
    #: so the preprocessor's "drop" decision matches the compiler's
    #: "accept" decision.
    _PRIORITY_NAME_ALIASES: dict[str, str] = {
        "stop_loss": "initial_stop",
    }

    def sanitize(self, raw: dict[str, Any]) -> tuple[dict[str, Any], _IRPreprocessReport]:
        """
        Return a deep-copied IR dict plus the diagnostic report.

        Args:
            raw: parsed IR dict (e.g. ``json.load(open(ir_file))``).
                Not mutated; the sanitiser deep-copies before editing.

        Returns:
            ``(sanitised_dict, report)`` -- the dict is suitable for
            :meth:`StrategyIR.model_validate`; the report lists every
            change made.
        """
        out = copy.deepcopy(raw)
        dropped_conditions: list[str] = []

        # 1. Strip unsupported leaves from long / short entry trees.
        for side in ("long", "short"):
            entry = out.get("entry_logic", {}).get(side)
            if entry is None:
                continue
            tree = entry.get("logic")
            if tree is None:
                continue
            entry["logic"] = self._strip_tree(
                tree, location_prefix=f"entry_logic.{side}.logic", drop_log=dropped_conditions
            )

        # 2. Strip unsupported entries from data_requirements.required_fields
        #    so the resolver does not allow them through into compile.
        dropped_fields: list[str] = []
        req = out.get("data_requirements", {})
        if isinstance(req.get("required_fields"), list):
            kept: list[str] = []
            for field in req["required_fields"]:
                if field in self._UNSUPPORTED_PRICE_FIELDS:
                    dropped_fields.append(field)
                    continue
                kept.append(field)
            req["required_fields"] = kept

        # 3. Filter same_bar_priority to entries that match a configured stop
        #    or an enabled wrapper rule (trailing_stop, time_exit). The
        #    compiler resolves the priority list strictly, so dropping
        #    here keeps the CLI from raising on IRs that list rules they
        #    do not actually configure (a common Strategy Repo pattern).
        dropped_priority: list[str] = []
        exit_logic = out.get("exit_logic", {})
        priority = exit_logic.get("same_bar_priority", [])
        configured: set[str] = set()
        for stop_name in (
            "primary_exit",
            "initial_stop",
            "take_profit",
            "trailing_exit",
            "scheduled_exit",
            "equity_stop",
        ):
            if exit_logic.get(stop_name) is not None:
                configured.add(stop_name)
        # Wrapper rules: TrailingStopRule + TimeExitRule become
        # compiler-recognised exit checks named "trailing_stop" and
        # "time_exit" when their ``enabled`` flag is True.
        trailing_stop = exit_logic.get("trailing_stop")
        if isinstance(trailing_stop, dict) and trailing_stop.get("enabled"):
            configured.add("trailing_stop")
        time_exit = exit_logic.get("time_exit")
        if isinstance(time_exit, dict) and time_exit.get("enabled"):
            configured.add("time_exit")
        kept_priority: list[str] = []
        for name in priority:
            canonical = self._PRIORITY_NAME_ALIASES.get(name, name)
            if canonical not in configured:
                dropped_priority.append(name)
                continue
            kept_priority.append(name)
        if "same_bar_priority" in exit_logic:
            exit_logic["same_bar_priority"] = kept_priority

        report = _IRPreprocessReport(
            dropped_conditions=tuple(dropped_conditions),
            dropped_required_fields=tuple(dropped_fields),
            dropped_priority_entries=tuple(dropped_priority),
        )
        return out, report

    def _strip_tree(
        self,
        tree: dict[str, Any],
        *,
        location_prefix: str,
        drop_log: list[str],
    ) -> dict[str, Any]:
        """
        Recursively remove unsupported leaves from a condition tree.

        Args:
            tree: ``{"op": "and"|"or", "conditions": [...]}`` dict.
            location_prefix: human-readable path used in drop_log
                entries so operators can find the offending leaf.
            drop_log: sink for dropped-leaf descriptions; appended to
                in place.

        Returns:
            A NEW tree dict with the unsupported leaves filtered out.
            If every leaf was unsupported, returns the tree with an
            empty ``conditions`` list -- the compiler will raise on
            an empty tree, surfacing the over-aggressive drop to the
            operator (rather than silently producing a strategy that
            never enters).
        """
        new_conditions: list[Any] = []
        for index, child in enumerate(tree.get("conditions", [])):
            child_loc = f"{location_prefix}.conditions[{index}]"
            if isinstance(child, dict) and "op" in child and "conditions" in child:
                # Nested tree.
                new_conditions.append(
                    self._strip_tree(
                        child,
                        location_prefix=child_loc,
                        drop_log=drop_log,
                    )
                )
                continue
            if isinstance(child, dict) and self._leaf_is_unsupported(child):
                drop_log.append(self._format_leaf(child, child_loc))
                continue
            new_conditions.append(child)
        new_tree = dict(tree)
        new_tree["conditions"] = new_conditions
        return new_tree

    def _leaf_is_unsupported(self, leaf: dict[str, Any]) -> bool:
        """
        Decide whether ``leaf`` references an identifier the compiler
        cannot yet evaluate.

        We only check for the bare-token form (``lhs == "spread"``,
        ``rhs == "spread"``) because the production IRs use that
        exact shape. Compound expressions (``"spread + 1.0"``) would
        require an AST walk; none of the IRs in scope use that form,
        so deferring it keeps the sanitiser focused.
        """
        for side in ("lhs", "rhs"):
            value = leaf.get(side)
            if isinstance(value, str) and value in self._UNSUPPORTED_PRICE_FIELDS:
                return True
        return False

    @staticmethod
    def _format_leaf(leaf: dict[str, Any], location: str) -> str:
        """Format a leaf condition into a one-line diagnostic string."""
        lhs = leaf.get("lhs", "?")
        op = leaf.get("operator", "?")
        rhs = leaf.get("rhs", "?")
        return f"{location}: {lhs} {op} {rhs}"


# ---------------------------------------------------------------------------
# IR-id indicator computer
# ---------------------------------------------------------------------------


class _IRIndicatorComputer:
    """
    Compute every IR-declared indicator per bar, returning a dict keyed
    by IR id (the shape :meth:`IRStrategy.evaluate` consumes).

    Why a dedicated class rather than a one-liner:
        IR indicators are typed (``SmaIndicator``, ``AtrIndicator``,
        ``BollingerUpperIndicator``...) and each has its own parameter
        names (``length`` vs. ``length_bars``, ``stddev``, etc.). The
        compiled :class:`IRStrategy` consumes a flat
        ``dict[str, IndicatorResult]`` keyed by the IR's per-indicator
        id. We need a translation table from IR shape -> default
        registry's calculator name + params + (for multi-component
        outputs like Bollinger) the component to extract. Encapsulating
        the translation here keeps :func:`main` readable and unit-
        testable in isolation.

    Does NOT:
        - Cache results across bars. Each call is independent (the
          compiled strategy receives a sliding window and re-computes
          indicators per bar -- that is the BacktestEngine convention
          this CLI mirrors so the M3.X1.5 parity test holds).
        - Compute cross-timeframe indicators. Those land with the
          M1.B6 multi-timeframe tranche.
    """

    def __init__(self, ir_indicators: Sequence[Indicator]) -> None:
        """
        Pre-resolve the per-indicator dispatch table.

        Args:
            ir_indicators: every indicator declared in the IR's
                ``indicators`` block. Stored as-is (frozen Pydantic
                models). The dispatch table is computed lazily on the
                first :meth:`compute` call so failures surface under
                the right operator and not at construction time.
        """
        self._indicators: tuple[Indicator, ...] = tuple(ir_indicators)

    def compute(self, candles: list[Candle]) -> dict[str, IndicatorResult]:
        """
        Compute every IR indicator over ``candles`` and return a dict
        keyed by IR id.

        Args:
            candles: chronological candle buffer for the symbol under
                evaluation. The compiled strategy expects the latest
                bar to be ``candles[-1]``.

        Returns:
            ``{ir_id: IndicatorResult}``. The :attr:`IndicatorResult.values`
            array is always single-output (the multi-component
            Bollinger result is split into ``upper`` / ``middle`` /
            ``lower`` views in this method so the IR's per-band ids
            map cleanly).

        Raises:
            SyntheticBacktestError: when an IR indicator references an
                unsupported type. The error names the indicator id and
                its declared type so the operator can fix the IR.

        Example:
            computer = _IRIndicatorComputer(ir.indicators)
            ind_dict = computer.compute(candle_buffer)
            # ind_dict["bb_upper_1"].values[-1] -> latest upper-band value
        """
        out: dict[str, IndicatorResult] = {}
        if not candles:
            return out
        for ind in self._indicators:
            try:
                result = self._compute_one(ind, candles)
            except SyntheticBacktestError:
                raise
            except Exception as exc:  # pragma: no cover -- defensive
                # Wrap unexpected calculator failures in our typed
                # exception so the CLI surfaces a clean message rather
                # than a stack trace from numpy or pydantic. Tests
                # exercise the supported indicator types directly.
                raise SyntheticBacktestError(
                    f"indicator {ind.id!r} (type={ind.type!r}) failed to compute: {exc}"
                ) from exc
            out[ind.id] = result
        return out

    def _compute_one(self, ind: Indicator, candles: list[Candle]) -> IndicatorResult:
        """
        Dispatch one indicator to the default registry's calculator
        and return a single-component :class:`IndicatorResult` keyed
        by the IR id.
        """
        if isinstance(ind, SmaIndicator):
            raw = default_engine.compute("SMA", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, EmaIndicator):
            raw = default_engine.compute("EMA", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, RsiIndicator):
            raw = default_engine.compute("RSI", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, AtrIndicator):
            raw = default_engine.compute("ATR", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, AdxIndicator):
            raw = default_engine.compute("ADX", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, BollingerUpperIndicator):
            raw = default_engine.compute(
                "BOLLINGER_BANDS",
                candles,
                period=ind.length,
                std_dev=ind.stddev,
            )
            return self._extract_component(ind.id, raw, "upper")
        if isinstance(ind, BollingerLowerIndicator):
            raw = default_engine.compute(
                "BOLLINGER_BANDS",
                candles,
                period=ind.length,
                std_dev=ind.stddev,
            )
            return self._extract_component(ind.id, raw, "lower")
        if isinstance(ind, RollingHighIndicator):
            raw = default_engine.compute("ROLLING_HIGH", candles, period=ind.length_bars)
            return self._rekey(ind.id, raw)
        if isinstance(ind, RollingLowIndicator):
            raw = default_engine.compute("ROLLING_LOW", candles, period=ind.length_bars)
            return self._rekey(ind.id, raw)
        if isinstance(ind, RollingMaxIndicator):
            raw = default_engine.compute("ROLLING_MAX", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, RollingMinIndicator):
            raw = default_engine.compute("ROLLING_MIN", candles, period=ind.length)
            return self._rekey(ind.id, raw)
        if isinstance(ind, RollingStddevIndicator):
            raw = default_engine.compute(
                "ROLLING_STDDEV",
                candles,
                period=ind.length_bars,
            )
            return self._rekey(ind.id, raw)
        if isinstance(ind, ZscoreIndicator):
            raw = default_engine.compute("ZSCORE", candles)
            return self._rekey(ind.id, raw)
        if isinstance(ind, (CalendarBusinessDayIndexIndicator, CalendarDaysToMonthEndIndicator)):
            # Calendar indicators are computed via the default engine's
            # CALENDAR_BUSINESS_DAY_INDEX / CALENDAR_DAYS_TO_MONTH_END
            # calculators registered in libs.indicators.calendar.
            registry_name = (
                "CALENDAR_BUSINESS_DAY_INDEX"
                if isinstance(ind, CalendarBusinessDayIndexIndicator)
                else "CALENDAR_DAYS_TO_MONTH_END"
            )
            raw = default_engine.compute(registry_name, candles)
            return self._rekey(ind.id, raw)
        raise SyntheticBacktestError(
            f"indicator {ind.id!r} has unsupported type {ind.type!r}; "
            "supported types in the M3.X1 CLI: sma, ema, rsi, atr, adx, "
            "bollinger_upper, bollinger_lower, rolling_high, rolling_low, "
            "rolling_max, rolling_min, rolling_stddev, zscore, "
            "calendar_business_day_index, calendar_days_to_month_end"
        )

    @staticmethod
    def _rekey(ir_id: str, raw: IndicatorResult) -> IndicatorResult:
        """Re-key a single-component result so the IR id is the canonical name."""
        return IndicatorResult(
            indicator_name=ir_id,
            values=raw.values,
            components={},
            timestamps=raw.timestamps,
            metadata=dict(raw.metadata),
        )

    @staticmethod
    def _extract_component(ir_id: str, raw: IndicatorResult, component: str) -> IndicatorResult:
        """
        Pull a named component out of a multi-output result and wrap
        it in a single-output :class:`IndicatorResult` keyed by the IR id.

        Used for Bollinger upper / lower extraction (and any future
        multi-output indicator the IR splits into multiple ids).
        """
        if component not in raw.components:
            raise SyntheticBacktestError(
                f"indicator {ir_id!r}: expected component {component!r} in "
                f"{raw.indicator_name} result; got components={list(raw.components)}"
            )
        return IndicatorResult(
            indicator_name=ir_id,
            values=raw.components[component],
            components={},
            timestamps=raw.timestamps,
            metadata=dict(raw.metadata),
        )


# ---------------------------------------------------------------------------
# Trade-pairing engine
# ---------------------------------------------------------------------------


@dataclass
class _TradeRecord:
    """
    Per-trade summary captured by :class:`_TradePairer`.

    A ``_TradeRecord`` is a single round-trip: an entry fill paired
    with the exit fill that flattened the position. Open positions at
    end-of-stream produce a record with ``exit_*`` fields set to
    ``None``.

    All Decimal arithmetic is preserved here; the JSON serialiser
    converts to strings with ``str(decimal)`` so the blotter is
    byte-deterministic without floating-point round-trip drift.

    Attributes:
        symbol: The instrument the trade was for.
        side: ``"long"`` if the entry was a BUY, ``"short"`` if SELL.
        units: Number of units entered; same units exit (no partials).
        entry_bar_index: Monotonic bar index from the paper broker
            (0-based) when the entry filled.
        entry_timestamp: Bar timestamp at entry fill.
        entry_price: Decimal fill price at entry (after slippage).
        exit_bar_index: Monotonic bar index at exit, or ``None``.
        exit_timestamp: Bar timestamp at exit, or ``None``.
        exit_price: Decimal fill price at exit, or ``None``.
        pnl: Realised PnL in account currency (long: exit-entry;
            short: entry-exit), or ``None`` for open positions.
        entry_extension_id: ``client_extension_id`` of the entry order.
        exit_extension_id: ``client_extension_id`` of the exit order,
            or ``None`` for open positions.
    """

    symbol: str
    side: str
    units: int
    entry_bar_index: int
    entry_timestamp: datetime
    entry_price: Decimal
    entry_extension_id: str
    exit_bar_index: int | None = None
    exit_timestamp: datetime | None = None
    exit_price: Decimal | None = None
    exit_extension_id: str | None = None
    pnl: Decimal | None = None


class _TradePairer:
    """
    Convert a stream of :class:`FillEvent`s into round-trip
    :class:`_TradeRecord`s.

    Pairing rule:
        Entry fills (signed direction matches the position the symbol
        is taking on) push onto a per-symbol open-trade FIFO. Exit
        fills (signed direction opposite to the open trade) pop the
        oldest open trade and stamp its ``exit_*`` fields. The CLI
        only ever places single-unit entries that fully flatten on
        exit (the M3.X1 sizing pragma), so the FIFO holds at most one
        trade per symbol at a time.

    Why FIFO rather than LIFO:
        FIFO is the IRS-recognised default and matches the BacktestEngine
        convention; tests are easier to read.

    Does NOT:
        - Track partial fills. The paper broker does not produce them.
        - Translate currency. PnL is in the broker's account currency
          (the paper broker uses USD).
    """

    def __init__(self) -> None:
        # Per-symbol FIFO of currently-open _TradeRecord (the entry
        # has filled, the exit hasn't). The list grows on entry and
        # shrinks on exit; both happen in the same submit_bar loop
        # iteration so there is no concurrency to worry about.
        self._open: dict[str, list[_TradeRecord]] = {}
        # All trades, in chronological completion order. Open trades
        # at end-of-stream are appended at finalisation time so the
        # ordering remains "entry-time within open-then-closed groups".
        self._closed: list[_TradeRecord] = []

    def record_fill(self, fill: FillEvent, bar_timestamp: datetime) -> None:
        """
        Update the per-symbol FIFO with one fill.

        Args:
            fill: The :class:`FillEvent` emitted by
                :meth:`PaperBrokerAdapter.submit_bar`.
            bar_timestamp: The bar's timestamp; stamped on the
                resulting trade record.
        """
        symbol = fill.symbol
        side_label = "long" if fill.side == OrderSide.BUY else "short"
        opens = self._open.setdefault(symbol, [])

        if not opens:
            # No open trade: this fill opens one.
            opens.append(
                _TradeRecord(
                    symbol=symbol,
                    side=side_label,
                    units=fill.units,
                    entry_bar_index=fill.bar_index,
                    entry_timestamp=bar_timestamp,
                    entry_price=fill.fill_price,
                    entry_extension_id=fill.order_ref.client_extension_id,
                )
            )
            return

        # An open trade exists; if this fill is the OPPOSITE direction
        # it closes the oldest open trade. Same-direction would scale
        # in (multiple opens). The CLI never scales in (one entry per
        # signal, sized at _PAPER_ORDER_UNITS) but we honour FIFO for
        # any future deviation.
        head = opens[0]
        opening_was_long = head.side == "long"
        this_is_close = (opening_was_long and fill.side == OrderSide.SELL) or (
            not opening_was_long and fill.side == OrderSide.BUY
        )
        if this_is_close:
            head.exit_bar_index = fill.bar_index
            head.exit_timestamp = bar_timestamp
            head.exit_price = fill.fill_price
            head.exit_extension_id = fill.order_ref.client_extension_id
            # Realised PnL: long = (exit-entry)*units, short = (entry-exit)*units.
            if opening_was_long:
                head.pnl = (head.exit_price - head.entry_price) * Decimal(head.units)
            else:
                head.pnl = (head.entry_price - head.exit_price) * Decimal(head.units)
            self._closed.append(head)
            opens.pop(0)
            return

        # Same direction -> scale in. Append; close still pops FIFO.
        opens.append(
            _TradeRecord(
                symbol=symbol,
                side=side_label,
                units=fill.units,
                entry_bar_index=fill.bar_index,
                entry_timestamp=bar_timestamp,
                entry_price=fill.fill_price,
                entry_extension_id=fill.order_ref.client_extension_id,
            )
        )

    def finalise(self) -> list[_TradeRecord]:
        """
        Return the closed trades plus any still-open positions.

        Open trades carry ``exit_*`` and ``pnl`` as ``None``; the
        blotter serialiser preserves that distinction.
        """
        out: list[_TradeRecord] = list(self._closed)
        for opens in self._open.values():
            out.extend(opens)
        return out


# ---------------------------------------------------------------------------
# Argparse + main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """
    Build the argparse parser.

    Why a dedicated builder:
        Tests construct the parser directly to assert help text and
        defaults without invoking :func:`main`. Keeping the builder
        separate keeps :func:`main`'s logic focused on orchestration.
    """
    parser = argparse.ArgumentParser(
        prog="python -m services.cli.run_synthetic_backtest",
        description=(
            "Run a single Strategy IR end-to-end against synthetic FX data and "
            "produce a deterministic JSON trade blotter (M3.X1)."
        ),
    )
    parser.add_argument(
        "--ir",
        required=True,
        type=Path,
        help="Path to a strategy_ir.json file.",
    )
    parser.add_argument(
        "--start",
        required=True,
        type=_parse_date,
        help="Inclusive UTC start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=_parse_date,
        help="Inclusive UTC end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--seed",
        required=True,
        type=int,
        help="Master seed for the synthetic provider; same seed = byte-identical output.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the trade blotter JSON.",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbol override; defaults to every IR "
        "universe symbol that the synthetic provider supports.",
    )
    parser.add_argument(
        "--timeframe",
        default=None,
        help="Override the IR's primary_timeframe (M15 / 15m / H1 / 1h / H4 / 4h / D / D1 / 1d).",
    )
    parser.add_argument(
        "--starting-balance",
        default="100000",
        type=Decimal,
        help="Starting paper-broker balance in account currency. Defaults to 100000.",
    )
    parser.add_argument(
        "--deployment-id",
        default="m3x1-cli",
        help="Deployment id stamped on every emitted Signal. Defaults to 'm3x1-cli'.",
    )
    return parser


def _parse_date(value: str) -> date:
    """
    argparse type-fn for --start / --end. Always returns a UTC ``date``.

    Raises:
        argparse.ArgumentTypeError: when ``value`` is not ``YYYY-MM-DD``.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point. Returns 0 on success, non-zero on failure.

    Args:
        argv: argument vector; defaults to ``sys.argv[1:]`` when None.
            Tests pass an explicit list so they do not touch process
            argv.

    Returns:
        Exit code:
            0 -- run completed and blotter written.
            2 -- :class:`SyntheticBacktestError` raised; message on stderr.

    Raises:
        Never. All errors are caught and translated to exit codes.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _run(args)
    except SyntheticBacktestError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    return 0


def _run(args: argparse.Namespace) -> None:
    """
    Orchestrate the full backtest by delegating to the executor.

    The CLI's job is now narrow: load + sanitise the IR, hand off to
    the :class:`SyntheticBacktestExecutor`, then serialise the
    executor's :class:`BacktestResult` plus the per-trade pairing
    records into the legacy JSON blotter format the M3.X1 smoke test
    consumes.

    Raises:
        SyntheticBacktestError: any expected failure path.
    """
    # Local import to break a small import cycle: the executor lives in
    # services.api.services and imports from this module's top half
    # (the shared helpers). Importing it lazily here keeps `python -m
    # services.cli.run_synthetic_backtest` working without pulling the
    # FastAPI stack at module-load time.
    from services.api.services.synthetic_backtest_executor import (
        SyntheticBacktestExecutor,
        SyntheticBacktestRequest,
    )

    # 1. Load + sanitise + validate the IR. Sanitisation is logged to
    #    stderr so the operator can audit what was dropped.
    ir, preprocess_report = _load_ir(args.ir)
    if (
        preprocess_report.dropped_conditions
        or preprocess_report.dropped_required_fields
        or preprocess_report.dropped_priority_entries
    ):
        sys.stderr.write(
            "ir-preprocess: dropped="
            f"{len(preprocess_report.dropped_conditions)} conditions, "
            f"{len(preprocess_report.dropped_required_fields)} required_fields, "
            f"{len(preprocess_report.dropped_priority_entries)} priority entries "
            "(see CLI module docstring for rationale)\n"
        )

    # 2. Resolve symbols + timeframe (used for blotter header echo and
    #    the executor's input bundle alike).
    symbols = _resolve_symbols(ir, args.symbols)
    timeframe = _resolve_timeframe(ir, args.timeframe)

    # 3. Execute via the shared orchestrator. We pass the SANITISED IR
    #    dict (json.loads of args.ir followed by the preprocessor) so
    #    the executor does not re-sanitise. The executor will validate
    #    StrategyIR a second time on the sanitised dict; that is cheap
    #    and keeps the two call sites symmetric.
    raw_ir_dict = json.loads(args.ir.read_text(encoding="utf-8"))
    request = SyntheticBacktestRequest(
        strategy_ir_dict=raw_ir_dict,
        symbols=symbols,
        timeframe=timeframe,
        start=args.start,
        end=args.end,
        seed=args.seed,
        starting_balance=args.starting_balance,
        deployment_id=args.deployment_id,
    )
    backtest_result = SyntheticBacktestExecutor().execute(request)

    # 4. The executor produced a BacktestResult, but the CLI's legacy
    #    JSON blotter format includes per-trade PnL and the entry/exit
    #    extension ids. Those live on the broker fills, not on
    #    BacktestResult. Re-walk the bars to rebuild the trade-pairer's
    #    records so the legacy format stays intact. The replay is
    #    deterministic (same seed, same broker) so the SHA-determinism
    #    contract holds.
    trade_records = _replay_for_trade_records(
        ir=ir,
        symbols=symbols,
        timeframe=timeframe,
        start=args.start,
        end=args.end,
        seed=args.seed,
        starting_balance=args.starting_balance,
        deployment_id=args.deployment_id,
    )

    blotter = _build_blotter(args, ir, symbols, timeframe, trade_records, backtest_result)
    _write_blotter(args.output, blotter)
    summary = _compute_summary_from_records(
        trade_records, backtest_result.final_equity, args.starting_balance
    )
    sys.stdout.write(_format_summary(summary))


# ---------------------------------------------------------------------------
# IR loading
# ---------------------------------------------------------------------------


def _load_ir(path: Path) -> tuple[StrategyIR, _IRPreprocessReport]:
    """
    Read ``path``, parse JSON, sanitise via :class:`_IRPreprocessor`,
    then validate via :meth:`StrategyIR.model_validate`.

    Args:
        path: filesystem path to the IR JSON file.

    Returns:
        ``(ir, report)``. The IR is the validated, immutable
        :class:`StrategyIR`; the report describes any sanitisation.

    Raises:
        SyntheticBacktestError: when the file does not exist, contains
            invalid JSON, or fails Pydantic validation. The exception
            message names the root cause so the operator can fix the
            IR without diff-hunting.
    """
    if not path.exists():
        raise SyntheticBacktestError(f"IR file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyntheticBacktestError(
            f"IR file {path} is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    sanitised, report = _IRPreprocessor().sanitize(raw)
    try:
        ir = StrategyIR.model_validate(sanitised)
    except Exception as exc:
        raise SyntheticBacktestError(
            f"IR file {path} failed schema validation: {type(exc).__name__}: {exc}"
        ) from exc
    return ir, report


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve_symbols(ir: StrategyIR, override: str | None) -> list[str]:
    """
    Decide which symbols the run will process.

    Priority:
        1. ``override`` (comma-separated string from --symbols).
        2. Otherwise the IR's universe.symbols intersected with the
           synthetic provider's supported set. Symbols outside the
           supported set are dropped (with a stderr note) rather than
           failing the run.

    Returns:
        Sorted list (deterministic ordering for downstream
        chronological replay).

    Raises:
        SyntheticBacktestError: when the resolved list is empty.
    """
    if override:
        candidates = [s.strip() for s in override.split(",") if s.strip()]
    else:
        candidates = list(ir.universe.symbols)
    supported = sorted(set(candidates) & _SYNTHETIC_SUPPORTED_SYMBOLS)
    if not supported:
        raise SyntheticBacktestError(
            f"no supported symbols among requested {candidates}; "
            f"synthetic provider supports: {sorted(_SYNTHETIC_SUPPORTED_SYMBOLS)}"
        )
    skipped = sorted(set(candidates) - _SYNTHETIC_SUPPORTED_SYMBOLS)
    if skipped:
        sys.stderr.write(f"symbols-skipped: {skipped} not modelled by synthetic provider\n")
    return supported


def _resolve_timeframe(ir: StrategyIR, override: str | None) -> str:
    """
    Decide which timeframe the run will pass to the synthetic provider.

    Priority:
        1. ``override`` (--timeframe value).
        2. The IR's ``data_requirements.primary_timeframe``.

    The result is normalised against
    :data:`_TIMEFRAME_NORMALISATION` so legacy IR strings like
    ``"4h"`` map to the provider's canonical ``"H4"`` form.

    Raises:
        SyntheticBacktestError: when the resolved string is not in
            the normalisation table.
    """
    raw = override if override is not None else ir.data_requirements.primary_timeframe
    if raw not in _TIMEFRAME_NORMALISATION:
        raise SyntheticBacktestError(
            f"unsupported timeframe {raw!r}; "
            f"synthetic provider accepts: {sorted(_TIMEFRAME_NORMALISATION)}"
        )
    return _TIMEFRAME_NORMALISATION[raw]


def _position_snapshot(
    broker: PaperBrokerAdapter, symbol: str, candle: Candle
) -> PositionSnapshot | None:
    """
    Convert the paper broker's :class:`Position` into the
    :class:`PositionSnapshot` shape the compiled strategy expects.

    Args:
        broker: source of position state.
        symbol: instrument to look up.
        candle: latest bar; supplies the mark price for unrealised PnL.

    Returns:
        :class:`PositionSnapshot` when the symbol has an open
        position; ``None`` when flat.
    """
    pos = broker.get_position(symbol)
    if pos is None:
        return None
    quantity = Decimal(pos.units)
    market_value = quantity * candle.close
    cost_basis = quantity * pos.average_price
    unrealised = market_value - cost_basis
    return PositionSnapshot(
        symbol=symbol,
        quantity=quantity,
        average_entry_price=pos.average_price,
        market_price=candle.close,
        market_value=market_value,
        unrealized_pnl=unrealised,
        cost_basis=cost_basis,
        updated_at=candle.timestamp,
    )


def _signal_to_order_side(
    signal_type: Any,
    direction: Any,
    position: PositionSnapshot | None,
) -> OrderSide | None:
    """
    Translate a :class:`Signal` into a paper-broker order side.

    Entry signals: open in the signal's declared direction.
    Exit signals: flatten the current position (no-op when flat).

    Returns ``None`` for exit signals with no open position; the
    caller skips placing the order.
    """
    if signal_type == SignalType.ENTRY:
        if direction == SignalDirection.LONG:
            return OrderSide.BUY
        if direction == SignalDirection.SHORT:
            return OrderSide.SELL
        return None
    if signal_type == SignalType.EXIT:
        if position is None or position.quantity == 0:
            return None
        if position.quantity > 0:
            return OrderSide.SELL
        return OrderSide.BUY
    # Anything else (SCALE_IN, SCALE_OUT, STOP_ADJUSTMENT) is out of
    # scope for the M3.X1 CLI -- those are tracked under M3.X2.
    return None


# ---------------------------------------------------------------------------
# Trade-record replay (legacy CLI blotter format)
# ---------------------------------------------------------------------------


def _replay_for_trade_records(
    *,
    ir: StrategyIR,
    symbols: list[str],
    timeframe: str,
    start: date,
    end: date,
    seed: int,
    starting_balance: Decimal,
    deployment_id: str,
) -> list[_TradeRecord]:
    """
    Re-run the deterministic pipeline to capture per-trade pairing
    records the legacy CLI blotter needs (entry/exit ext_ids + pnl).

    The executor returns a typed ``BacktestResult`` which does not
    carry these per-fill metadata. Rather than complicate the executor's
    return shape (it is the API-facing contract), the CLI re-runs the
    same deterministic pipeline locally to capture the trade pairer's
    output. Because both runs use the same seed against the same
    synthetic provider, both produce byte-identical broker streams,
    so the per-trade records the CLI prints match the executor's
    BacktestResult.

    Args:
        ir: The validated, sanitised IR.
        symbols: The resolved symbol list from :func:`_resolve_symbols`.
        timeframe: The normalised timeframe string.
        start: Inclusive UTC start date.
        end: Inclusive UTC end date.
        seed: Master seed.
        starting_balance: Paper-broker starting balance.
        deployment_id: Deployment id stamped on emitted Signals.

    Returns:
        List of :class:`_TradeRecord` (closed first, then open).
    """
    # Local imports to avoid pulling these into module-load time.
    from libs.strategy_ir.broker import NullBroker
    from libs.strategy_ir.clock import BarClock
    from libs.strategy_ir.compiler import StrategyIRCompiler
    from libs.strategy_ir.interfaces.broker_adapter_interface import OrderType
    from libs.strategy_ir.synthetic_market_data_provider import (
        SyntheticFxMarketDataProvider,
    )

    provider = SyntheticFxMarketDataProvider(seed=seed)
    broker = PaperBrokerAdapter(starting_balance=starting_balance, market_data=provider)
    clock = BarClock()
    compiled = StrategyIRCompiler(clock=clock, broker=NullBroker()).compile(
        ir, deployment_id=deployment_id
    )
    indicator_computer = _IRIndicatorComputer(ir.indicators)
    pairer = _TradePairer()

    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)
    all_candles: list[Candle] = []
    for symbol in symbols:
        all_candles.extend(
            provider.fetch_bars(symbol=symbol, timeframe=timeframe, start=start_dt, end=end_dt)
        )
    all_candles.sort(key=lambda c: (c.timestamp, c.symbol))

    per_symbol_buf: dict[str, list[Candle]] = {sym: [] for sym in symbols}
    correlation_id = f"m3x1-cli-{seed}"
    extension_counter = 0

    for candle in all_candles:
        symbol = candle.symbol
        buf = per_symbol_buf[symbol]
        buf.append(candle)
        if len(buf) > 600:
            del buf[: len(buf) - 600]

        fills = broker.submit_bar(symbol, candle)
        for fill in fills:
            pairer.record_fill(fill, candle.timestamp)

        indicators = indicator_computer.compute(buf)
        position_snapshot = _position_snapshot(broker, symbol, candle)
        signal = compiled.evaluate(
            symbol,
            buf,
            indicators,
            position_snapshot,
            correlation_id=correlation_id,
        )
        if signal is None:
            continue
        side = _signal_to_order_side(signal.signal_type, signal.direction, position_snapshot)
        if side is None:
            continue
        extension_counter += 1
        ext_id = f"{correlation_id}-{extension_counter:08d}"
        broker.place_order(
            symbol,
            side,
            _PAPER_ORDER_UNITS,
            order_type=OrderType.MARKET,
            client_extension_id=ext_id,
        )

    return pairer.finalise()


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _build_blotter(
    args: argparse.Namespace,
    ir: StrategyIR,
    symbols: list[str],
    timeframe: str,
    trades: list[_TradeRecord],
    backtest_result: Any,
) -> dict[str, Any]:
    """
    Compose the blotter dict that gets serialised to JSON.

    Why a dedicated builder:
        Keeping the dict shape in one place makes the determinism
        contract obvious -- every field is either a primitive or a
        ``str(decimal)`` / ``isoformat()`` rendering of a deterministic
        input.

    Returns:
        Dict with keys ``run`` (config + ir id), ``trades``
        (chronological list), ``open_positions`` (any unclosed
        position at end-of-stream), ``ending_balance`` (str-decimal).
    """
    trade_records: list[dict[str, Any]] = []
    for trade in trades:
        if trade.exit_timestamp is None:
            # Open trade: surface separately under open_positions.
            continue
        trade_records.append(
            {
                "symbol": trade.symbol,
                "side": trade.side,
                "units": trade.units,
                "entry_bar_index": trade.entry_bar_index,
                "entry_timestamp": trade.entry_timestamp.isoformat(),
                "entry_price": str(trade.entry_price),
                "entry_extension_id": trade.entry_extension_id,
                "exit_bar_index": trade.exit_bar_index,
                "exit_timestamp": (
                    trade.exit_timestamp.isoformat() if trade.exit_timestamp else None
                ),
                "exit_price": str(trade.exit_price) if trade.exit_price is not None else None,
                "exit_extension_id": trade.exit_extension_id,
                "pnl": str(trade.pnl) if trade.pnl is not None else None,
            }
        )

    open_records: list[dict[str, Any]] = []
    for trade in trades:
        if trade.exit_timestamp is not None:
            continue
        open_records.append(
            {
                "symbol": trade.symbol,
                "side": trade.side,
                "units": trade.units,
                "entry_bar_index": trade.entry_bar_index,
                "entry_timestamp": trade.entry_timestamp.isoformat(),
                "entry_price": str(trade.entry_price),
                "entry_extension_id": trade.entry_extension_id,
            }
        )

    return {
        "run": {
            "ir_strategy_name": ir.metadata.strategy_name,
            "ir_strategy_version": ir.metadata.strategy_version,
            "deployment_id": args.deployment_id,
            "seed": args.seed,
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "symbols": symbols,
            "timeframe": timeframe,
            "starting_balance": str(args.starting_balance),
        },
        "trades": trade_records,
        "open_positions": open_records,
        "ending_balance": str(backtest_result.final_equity),
    }


def _write_blotter(path: Path, blotter: dict[str, Any]) -> None:
    """
    Write ``blotter`` to ``path`` as canonical JSON.

    Canonical means ``sort_keys=True`` + 2-space indent + trailing
    newline. Two runs with the same inputs therefore produce
    byte-identical files; a hash check is sufficient for the
    determinism assertion in the smoke test.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(blotter, sort_keys=True, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RunSummary:
    """
    End-of-run aggregate metrics printed to stdout.

    Decimal-typed fields are rendered as plain strings in
    :func:`_format_summary` so the printed output stays byte-stable.
    """

    total_trades: int
    win_rate: float
    total_return_pct: float
    sharpe: float


def _compute_summary_from_records(
    trades: list[_TradeRecord],
    ending_balance: Decimal,
    starting_balance: Decimal,
) -> _RunSummary:
    """
    Compute the aggregate metrics from the closed-trade list.

    win_rate: closed trades with positive PnL / total closed trades.
    total_return_pct: (ending_balance - starting_balance) / starting * 100.
    sharpe: per-trade-PnL Sharpe ratio (mean / stdev * sqrt(N)) using
        sample stdev (ddof=1). Returns 0.0 when fewer than 2 trades or
        zero variance -- there is no meaningful Sharpe in those cases.

    Returns:
        :class:`_RunSummary`.
    """
    closed = [t for t in trades if t.pnl is not None]
    if not closed:
        return _RunSummary(total_trades=0, win_rate=0.0, total_return_pct=0.0, sharpe=0.0)

    wins = sum(1 for t in closed if t.pnl is not None and t.pnl > Decimal(0))
    win_rate = wins / len(closed) if closed else 0.0

    total_return_pct = (
        float((ending_balance - starting_balance) / starting_balance) * 100.0
        if starting_balance > Decimal(0)
        else 0.0
    )

    pnls = [float(t.pnl) for t in closed if t.pnl is not None]
    if len(pnls) < 2:
        sharpe = 0.0
    else:
        mean = sum(pnls) / len(pnls)
        # Sample variance (ddof=1) so the Sharpe matches numpy's
        # default and the BacktestEngine convention.
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        sharpe = 0.0 if var <= 0.0 else mean / math.sqrt(var) * math.sqrt(len(pnls))

    return _RunSummary(
        total_trades=len(closed),
        win_rate=win_rate,
        total_return_pct=total_return_pct,
        sharpe=sharpe,
    )


def _format_summary(summary: _RunSummary) -> str:
    """
    Render :class:`_RunSummary` as a human-readable multi-line string.

    Format: one metric per line, name and value separated by ``=``, six
    decimal places of precision so the printed output is byte-stable
    when the underlying floats are.
    """
    lines = [
        f"total_trades={summary.total_trades}",
        f"win_rate={summary.win_rate:.6f}",
        f"total_return_pct={summary.total_return_pct:.6f}",
        f"sharpe={summary.sharpe:.6f}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

__all__ = [
    "main",
    "SyntheticBacktestError",
]


if __name__ == "__main__":  # pragma: no cover -- module entry point
    raise SystemExit(main())
