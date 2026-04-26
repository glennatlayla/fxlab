"""
Side-by-side backtest of every production Strategy IR (M3.X1 multi-strategy report).

Purpose:
    Run every production Strategy IR (every ``*.strategy_ir.json`` file
    under ``Strategy Repo/``) through the deterministic synthetic-FX
    backtest pipeline, capture the headline metrics + a SHA-256 of the
    per-strategy blotter, and emit two artefacts:

      * A JSON report (``--output``) containing one record per strategy.
        Field ordering and value formatting are stable so two runs over
        the same inputs produce a byte-identical file.
      * A Markdown comparison table on stdout, sized to display cleanly
        in a 100-column terminal AND inside a GitHub PR description.

    The CLI is a pure orchestrator: it constructs the executor inputs
    for each IR and delegates execution to
    :class:`services.api.services.synthetic_backtest_executor.SyntheticBacktestExecutor`.
    No bar replay, no compiler invocation, no broker/provider wiring is
    re-implemented here -- the executor is the single source of truth for
    the pipeline shape.

Determinism contract:
    Same set of IR files + same window + same seed = byte-identical
    JSON report on every run. The CLI itself never reads a wall clock,
    never calls a random number generator, and never touches the
    network. Per-strategy blotter SHA-256s are computed over the
    canonical ``BacktestResult`` dump so a single broker-stream byte
    drift in any strategy is instantly visible.

Pipeline (per IR):
    1.  Read the IR JSON file (``json.loads`` only -- the executor
        sanitises the dict internally).
    2.  Build a :class:`SyntheticBacktestRequest` with the configured
        window + seed and an empty symbol list (executor falls back to
        ``ir.universe.symbols`` automatically).
    3.  Invoke :meth:`SyntheticBacktestExecutor.execute`.
    4.  Capture the headline metrics into a :class:`_StrategyResult` and
        compute a SHA-256 over the deterministic JSON dump of the
        :class:`BacktestResult` (canonical sorted-keys / 2-space indent /
        decimal-as-string serialisation).

Responsibilities:
    - Argparse: ``--ir-glob``, ``--start``, ``--end``, ``--seed``,
      ``--output``, ``--starting-balance``.
    - Iterate matching IR files in deterministic (sorted) order so the
      report's row ordering is reproducible.
    - Aggregate per-strategy metrics + blotter SHA into a JSON report.
    - Format a Markdown table to stdout that fits ~100 cols and renders
      cleanly when pasted into GitHub.

Does NOT:
    - Re-implement the backtest pipeline. The executor is the single
      source of truth.
    - Persist any state beyond the ``--output`` file.
    - Read any environment variable. All knobs come from CLI flags.
    - Touch the network, an external broker, or any database.
    - Provide a Python public API beyond :func:`main`. This module is
      invoked exclusively via
      ``python -m services.cli.backtest_all_strategies``.

Dependencies (all imported, none injected):
    - :mod:`services.api.services.synthetic_backtest_executor` -- the
      reusable orchestrator (see M2.D3).
    - :mod:`services.cli.run_synthetic_backtest` -- shared
      ``SyntheticBacktestError`` (re-exported from the executor
      module) for the failure exit path.

Raises:
    - :class:`services.cli.run_synthetic_backtest.SyntheticBacktestError`:
      caught at :func:`main` and translated to exit code 2 with a
      stderr message that names the offending IR file.

Example:
    .venv/bin/python -m services.cli.backtest_all_strategies \\
        --ir-glob 'Strategy Repo/*/*.strategy_ir.json' \\
        --start 2026-01-01 --end 2026-04-01 --seed 42 \\
        --output /tmp/backtest_comparison.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from libs.contracts.backtest import BacktestResult
from services.api.services.synthetic_backtest_executor import (
    SyntheticBacktestExecutor,
    SyntheticBacktestRequest,
)
from services.cli.run_synthetic_backtest import SyntheticBacktestError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: Default glob covering every production Strategy IR. Sized to match the
#: current Strategy Repo layout (one folder per strategy pack, one IR file
#: per strategy). Override via ``--ir-glob`` for ad-hoc subsets.
_DEFAULT_IR_GLOB: str = "Strategy Repo/*/*.strategy_ir.json"

#: Default backtest window. 2026-01-01 -> 2026-04-01 mirrors the M3.X1
#: smoke test's "production" window and stays within the synthetic
#: provider's modelled regime.
_DEFAULT_START: str = "2026-01-01"
_DEFAULT_END: str = "2026-04-01"

#: Default master seed. 42 matches the M3.X1 CLI default so blotters
#: produced by both CLIs hash to comparable values for the same window.
_DEFAULT_SEED: int = 42

#: Default destination for the JSON report.
_DEFAULT_OUTPUT: str = "/tmp/backtest_comparison.json"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StrategyResult:
    """
    Per-strategy summary captured by the multi-strategy backtest CLI.

    All Decimal-typed metrics are stored as strings to preserve the
    byte-determinism contract (``str(Decimal)`` is stable; round-tripping
    through ``float`` is not).

    Attributes:
        ir_path: Project-relative path of the IR file the result is for.
            Sorted relative to the current working directory so two
            machines running the CLI from the project root produce
            identical paths in the report.
        strategy_name: ``ir.metadata.strategy_name`` from the IR.
        strategy_version: ``ir.metadata.strategy_version`` from the IR.
        symbols: The symbols the executor actually replayed (intersection
            of the IR universe and the synthetic provider's supported
            set).
        timeframe: The normalised primary timeframe the executor used.
        bars_processed: Number of bars the executor evaluated.
        trade_count: Round-trip trade count (entry+exit pairs).
        total_return_pct: Headline total return percentage as a string.
        sharpe_ratio: Per-trade-PnL Sharpe ratio as a string.
        max_drawdown_pct: Max equity drawdown percentage as a string
            (always <= 0).
        win_rate: Fraction of winning trades (0-1) as a string.
        profit_factor: Gross profit / gross loss as a string.
        final_equity: Ending portfolio equity as a string.
        blotter_sha256: SHA-256 of the canonical-JSON dump of the
            executor's :class:`BacktestResult`. The hash digests the
            entire result (config + trades + equity_curve + metrics) so
            a regression in any deterministic surface flips it.
    """

    ir_path: str
    strategy_name: str
    strategy_version: str
    symbols: list[str]
    timeframe: str
    bars_processed: int
    trade_count: int
    total_return_pct: str
    sharpe_ratio: str
    max_drawdown_pct: str
    win_rate: str
    profit_factor: str
    final_equity: str
    blotter_sha256: str


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    """
    Argparse type-fn for ``--start`` / ``--end``. Returns a UTC ``date``.

    Raises:
        argparse.ArgumentTypeError: when ``value`` is not ``YYYY-MM-DD``.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def _build_parser() -> argparse.ArgumentParser:
    """
    Build the argparse parser.

    Why a dedicated builder:
        Tests construct the parser directly to assert defaults and help
        text without invoking :func:`main`. Keeping the builder
        separate also keeps :func:`main`'s logic focused on
        orchestration.
    """
    parser = argparse.ArgumentParser(
        prog="python -m services.cli.backtest_all_strategies",
        description=(
            "Run every production Strategy IR through the synthetic-FX "
            "backtest pipeline and emit a side-by-side comparison report "
            "(JSON file + Markdown table on stdout). Determinism: same IRs "
            "+ same window + same seed = byte-identical JSON report."
        ),
    )
    parser.add_argument(
        "--ir-glob",
        default=_DEFAULT_IR_GLOB,
        help=(
            f"Glob pattern matching the Strategy IR files to run. Defaults to {_DEFAULT_IR_GLOB!r}."
        ),
    )
    parser.add_argument(
        "--start",
        default=_DEFAULT_START,
        type=_parse_date,
        help=f"Inclusive UTC start date (YYYY-MM-DD). Defaults to {_DEFAULT_START}.",
    )
    parser.add_argument(
        "--end",
        default=_DEFAULT_END,
        type=_parse_date,
        help=f"Inclusive UTC end date (YYYY-MM-DD). Defaults to {_DEFAULT_END}.",
    )
    parser.add_argument(
        "--seed",
        default=_DEFAULT_SEED,
        type=int,
        help=(
            "Master seed for the synthetic provider; same seed = "
            f"byte-identical output. Defaults to {_DEFAULT_SEED}."
        ),
    )
    parser.add_argument(
        "--output",
        default=Path(_DEFAULT_OUTPUT),
        type=Path,
        help=f"Path to write the JSON comparison report. Defaults to {_DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--starting-balance",
        default=Decimal("100000"),
        type=Decimal,
        help="Starting paper-broker balance per strategy. Defaults to 100000.",
    )
    return parser


# ---------------------------------------------------------------------------
# Per-strategy execution
# ---------------------------------------------------------------------------


def _discover_ir_files(pattern: str) -> list[Path]:
    """
    Resolve ``pattern`` into a sorted list of IR file paths.

    Args:
        pattern: Glob string (recursive globs via ``**`` are supported
            because we pass ``recursive=True`` to :func:`glob.glob`).

    Returns:
        Sorted list of :class:`Path` objects -- sorting is what keeps
        the report's row ordering byte-deterministic across machines.

    Raises:
        SyntheticBacktestError: when the pattern matches zero files.
            A typo in ``--ir-glob`` is the most common operator error
            and silent zero-match would produce a misleading "all
            green" report.
    """
    matches = sorted(glob.glob(pattern, recursive=True))
    if not matches:
        raise SyntheticBacktestError(
            f"--ir-glob matched zero files: {pattern!r}; "
            "check the pattern is relative to the current working "
            "directory and that Strategy Repo/ is present."
        )
    return [Path(m) for m in matches]


#: BacktestResult fields that are NOT deterministic between two runs over
#: the same inputs and must therefore be excluded from the blotter hash.
#: ``computed_at`` is a wall-clock timestamp stamped by the executor when
#: the result is constructed; it varies per call by definition. Every
#: other field on the result is a pure function of the IR + window + seed.
_NON_DETERMINISTIC_RESULT_FIELDS: frozenset[str] = frozenset({"computed_at"})


def _hash_backtest_result(result: BacktestResult) -> str:
    """
    Compute a SHA-256 over the canonical JSON dump of a BacktestResult,
    excluding fields whose value is set from the wall clock.

    Why hash the whole result rather than just trades:
        The trade list alone would miss equity-curve drift and headline-
        metric drift. A whole-result hash catches every deterministic
        surface in one digest, which is exactly the behaviour the
        smoke-test "byte identical across runs" assertion needs.

    Why we strip ``computed_at`` (and any future wall-clock field):
        :class:`BacktestResult` stamps ``computed_at`` from
        :func:`datetime.utcnow` when it is constructed. Including it in
        the hash would break determinism by design. The configured
        :data:`_NON_DETERMINISTIC_RESULT_FIELDS` set documents every
        excluded field so a future drift never sneaks in unnoticed.

    Args:
        result: The :class:`BacktestResult` to hash.

    Returns:
        Lower-case hex SHA-256 string.
    """
    payload = result.model_dump(mode="json")
    for excluded in _NON_DETERMINISTIC_RESULT_FIELDS:
        payload.pop(excluded, None)
    encoded = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _execute_one(
    *,
    ir_path: Path,
    start: date,
    end: date,
    seed: int,
    starting_balance: Decimal,
) -> _StrategyResult:
    """
    Run one IR through the executor and pack the headline metrics into
    a :class:`_StrategyResult`.

    Args:
        ir_path: IR file to read.
        start: Inclusive UTC start date for the replay window.
        end: Inclusive UTC end date for the replay window.
        seed: Master seed for the synthetic provider.
        starting_balance: Per-strategy paper-broker starting balance.

    Returns:
        A :class:`_StrategyResult` ready for serialisation.

    Raises:
        SyntheticBacktestError: when the IR file does not exist, the
            JSON cannot be parsed, or the executor rejects the run.
            The message names the offending IR path so the operator
            can fix the input without diff-hunting.
    """
    if not ir_path.exists():
        raise SyntheticBacktestError(f"IR file not found: {ir_path}")
    try:
        ir_dict = json.loads(ir_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyntheticBacktestError(
            f"IR file {ir_path} is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc

    # Pass an empty symbol list so the executor falls back to the IR's
    # universe.symbols. Pass the IR's own primary_timeframe via a
    # neutral value -- the executor's _resolve_timeframe normalises it.
    primary_timeframe = ir_dict.get("data_requirements", {}).get("primary_timeframe", "H1")
    request = SyntheticBacktestRequest(
        strategy_ir_dict=ir_dict,
        symbols=[],
        timeframe=primary_timeframe,
        start=start,
        end=end,
        seed=seed,
        starting_balance=starting_balance,
        deployment_id="m3x1-multi-cli",
    )
    result = SyntheticBacktestExecutor().execute(request)

    metadata = ir_dict.get("metadata", {})
    return _StrategyResult(
        ir_path=str(ir_path),
        strategy_name=str(metadata.get("strategy_name", "")),
        strategy_version=str(metadata.get("strategy_version", "")),
        symbols=list(result.config.symbols),
        timeframe=primary_timeframe,
        bars_processed=int(result.bars_processed),
        trade_count=int(result.total_trades),
        total_return_pct=str(result.total_return_pct),
        sharpe_ratio=str(result.sharpe_ratio),
        max_drawdown_pct=str(result.max_drawdown_pct),
        win_rate=str(result.win_rate),
        profit_factor=str(result.profit_factor),
        final_equity=str(result.final_equity),
        blotter_sha256=_hash_backtest_result(result),
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _build_report(
    *,
    args: argparse.Namespace,
    ir_files: list[Path],
    results: list[_StrategyResult],
) -> dict[str, Any]:
    """
    Compose the JSON report dict.

    The report is intentionally flat: a ``run`` block describing the
    config, then a ``strategies`` list with one record per IR.

    Returns:
        Dict ready to be passed to :func:`_write_report`.
    """
    return {
        "run": {
            "ir_glob": args.ir_glob,
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "seed": args.seed,
            "starting_balance": str(args.starting_balance),
            "ir_files": [str(p) for p in ir_files],
        },
        "strategies": [asdict(r) for r in results],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    """
    Write ``report`` to ``path`` as canonical JSON.

    Canonical means ``sort_keys=True`` + 2-space indent + trailing
    newline. Two runs with the same inputs therefore produce
    byte-identical files; a hash check is sufficient for the
    determinism assertion in the smoke test.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")


def _format_markdown_table(results: list[_StrategyResult]) -> str:
    """
    Render the per-strategy results as a Markdown table.

    Layout:
        | Strategy | Trades | Return % | Sharpe | MaxDD % | Win Rate | Profit Factor | Final Equity | Blotter SHA |

    Why a fixed column set:
        These eight metrics are the M3.X1 acceptance contract -- adding
        more bloats the row past 100 cols and breaks both terminal
        rendering and GitHub's PR description width.

    The blotter SHA is truncated to its first 12 hex chars so the
    column stays narrow; the full SHA is preserved in the JSON report.

    Returns:
        A multi-line string ending in ``\\n``.
    """
    if not results:
        return "_(no strategies in report)_\n"

    headers = [
        "Strategy",
        "Trades",
        "Return %",
        "Sharpe",
        "MaxDD %",
        "Win Rate",
        "Profit Factor",
        "Final Equity",
        "Blotter SHA",
    ]
    rows: list[list[str]] = []
    for r in results:
        rows.append(
            [
                r.strategy_name or Path(r.ir_path).stem,
                str(r.trade_count),
                r.total_return_pct,
                r.sharpe_ratio,
                r.max_drawdown_pct,
                r.win_rate,
                r.profit_factor,
                r.final_equity,
                r.blotter_sha256[:12],
            ]
        )

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point. Returns 0 on success, non-zero on failure.

    Args:
        argv: argument vector; defaults to ``sys.argv[1:]`` when None.
            Tests pass an explicit list so they do not touch process
            argv.

    Returns:
        Exit code:
            0 -- run completed and report written.
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
    Orchestrate IR discovery, per-strategy execution, and output.

    Raises:
        SyntheticBacktestError: any expected failure path. Per-strategy
            failures fail the whole run -- a partial comparison report
            would be more dangerous than no report at all (operators
            reading the table would not know which row is "all green
            because we skipped you").
    """
    if args.end < args.start:
        raise SyntheticBacktestError(f"end ({args.end}) precedes start ({args.start})")

    ir_files = _discover_ir_files(args.ir_glob)
    sys.stderr.write(f"discovered: {len(ir_files)} IR file(s) matching {args.ir_glob!r}\n")

    results: list[_StrategyResult] = []
    for ir_path in ir_files:
        sys.stderr.write(f"running: {ir_path}\n")
        try:
            result = _execute_one(
                ir_path=ir_path,
                start=args.start,
                end=args.end,
                seed=args.seed,
                starting_balance=args.starting_balance,
            )
        except SyntheticBacktestError as exc:
            # Re-raise with the offending file name baked in so the
            # operator does not have to scroll up to find it.
            raise SyntheticBacktestError(f"{ir_path}: {exc}") from exc
        results.append(result)

    report = _build_report(args=args, ir_files=ir_files, results=results)
    _write_report(args.output, report)
    sys.stdout.write(_format_markdown_table(results))
    sys.stderr.write(f"wrote: {args.output}\n")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover -- module entry point
    raise SystemExit(main())
