"""
Smoke tests for ``services.cli.backtest_all_strategies``.

The single end-to-end smoke test runs the multi-strategy CLI against
ALL five production IRs over a 45-day window. After the M3.X2.5
basket-execution + zscore-source wire-up tranche every production IR
runs through the executor end-to-end, so the smoke set is the full
production sweep with a shorter window than ``make backtest-all``'s
default (which is the 60-90 day production sweep).

Asserts:

    1. The CLI returns exit code 0.
    2. The output JSON has the expected top-level shape and one record
       per IR file with every metric field populated.
    3. The Markdown table on stdout contains a header row + one data
       row per strategy.
    4. Re-running the CLI with the same arguments produces a
       byte-identical JSON report (the CLAUDE.md §0 determinism
       contract) and the per-strategy blotter SHA-256s match across
       the two runs.

Budget: the test must finish in <60s. The window was sized so that
the basket strategies traverse at least one month-end calendar event
(needed for FX_TurnOfMonth to produce trades) without exceeding budget.

Dependencies:
    - :mod:`services.cli.backtest_all_strategies` -- module under test.
    - :mod:`pytest` for ``tmp_path`` and assertion helpers.

Does NOT:
    - Touch the network, an external broker, or any database.
    - Mock the executor. The whole purpose is to exercise the real
      pipeline end-to-end across multiple IRs.
"""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from services.cli import backtest_all_strategies as cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: Project root resolved relative to this file. Tests are at
#: tests/unit/services/cli/<file>.py so parents[4] is the repo root.
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

#: All five production IRs. After the M3.X2.5 basket-execution wire-up
#: (and the M1.B2-zscore parameter fix shipped in the same tranche),
#: every production IR runs through the executor end-to-end. The smoke
#: test exercises all five so a regression in any one indicator
#: capability or basket-exit evaluator surfaces in CI.
#:
#: Window is widened to 45 days so the D1 IRs (TurnOfMonth +
#: TimeSeriesMomentum) traverse at least one month-end calendar event;
#: the H1/H4 IRs run within the same window without exceeding the
#: 60s budget called out in the M3.X2.5 task brief.
_SMOKE_IR_PATHS: tuple[Path, ...] = (
    _PROJECT_ROOT
    / "Strategy Repo"
    / "fxlab_chan_next3_strategy_pack"
    / "FX_SingleAsset_MeanReversion_H1.strategy_ir.json",
    _PROJECT_ROOT
    / "Strategy Repo"
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TimeSeriesMomentum_Breakout_D1.strategy_ir.json",
    _PROJECT_ROOT
    / "Strategy Repo"
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TurnOfMonth_USDSeasonality_D1.strategy_ir.json",
    _PROJECT_ROOT
    / "Strategy Repo"
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_DoubleBollinger_TrendZone.strategy_ir.json",
    _PROJECT_ROOT
    / "Strategy Repo"
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json",
)

#: 45-day window keeps the test under the 60s budget while exercising
#: warm-up, indicator computation, basket entries (TurnOfMonth needs
#: at least one month-end), and several bars of strategy evaluation.
_START_DATE: str = "2026-01-01"
_END_DATE: str = "2026-02-15"
_SEED: int = 42


def _run_cli(
    output_path: Path, ir_files: tuple[Path, ...] = _SMOKE_IR_PATHS
) -> tuple[int, str, str]:
    """
    Invoke :func:`cli.main` with the smoke argument set and capture
    exit code + stdout + stderr.

    The CLI's ``--ir-glob`` flag accepts a glob string; for the smoke
    test we synthesise a temporary directory containing symlinks to
    the two chosen IR files so the glob matches exactly those two and
    nothing else. This isolates the test from changes to the Strategy
    Repo layout.

    Args:
        output_path: Where the CLI should write its JSON report.
        ir_files: Concrete IR files to expose to the CLI via symlinks.

    Returns:
        ``(exit_code, stdout, stderr)``.
    """
    # Create a side-by-side staging directory so the glob picks up only
    # the two IRs we chose. tmp_path-derived directories are unique per
    # test, so two parallel invocations cannot collide.
    staging = output_path.parent / "ir_staging"
    staging.mkdir(parents=True, exist_ok=True)
    for ir in ir_files:
        link = staging / ir.name
        if not link.exists():
            # Symlinks let us avoid copying ~6 KB per file; they also
            # make the staging directory's contents byte-identical to
            # the source IRs so the executor sees the same bytes.
            link.symlink_to(ir)

    argv = [
        "--ir-glob",
        str(staging / "*.strategy_ir.json"),
        "--start",
        _START_DATE,
        "--end",
        _END_DATE,
        "--seed",
        str(_SEED),
        "--output",
        str(output_path),
    ]
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        exit_code = cli.main(argv)
    return exit_code, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# Smoke test -- exit-code + report shape + Markdown + determinism
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_smoke_against_two_irs_produces_deterministic_report(tmp_path: Path) -> None:
    """
    End-to-end exercise of the multi-strategy CLI.

    Asserts:
        - Both IR fixtures exist (otherwise the test is meaningless).
        - First invocation returns exit 0.
        - Output JSON has the expected top-level keys: ``run`` (dict)
          and ``strategies`` (list with one record per IR).
        - Each strategy record has every field the
          :class:`_StrategyResult` dataclass declares.
        - Stdout contains the Markdown table header + one row per
          strategy + the eight expected metric column names.
        - Second invocation with the SAME arguments produces a
          byte-identical JSON report (SHA-256 equality) AND every
          per-strategy blotter SHA-256 matches across the two runs.
    """
    for ir_path in _SMOKE_IR_PATHS:
        assert ir_path.exists(), (
            f"IR fixture not found at {ir_path}; the smoke test cannot "
            "run without it. The repo includes this file under "
            "Strategy Repo/; if it is missing, restore from git history."
        )

    output_path = tmp_path / "report.json"
    exit_code, stdout, stderr = _run_cli(output_path)

    # 1. Exit code: must be 0 for downstream tooling to consider the
    #    run successful. Surface stderr in the failure message so the
    #    operator sees the executor's diagnostic on regression.
    assert exit_code == 0, f"CLI exited with {exit_code}; stdout={stdout!r}; stderr={stderr!r}"

    # 2. Output file structure.
    assert output_path.exists(), "CLI did not produce the --output file"
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(report, dict), "report must be a JSON object"
    for key in ("run", "strategies"):
        assert key in report, f"report missing top-level key {key!r}"

    assert isinstance(report["run"], dict), "report.run must be a dict"
    assert isinstance(report["strategies"], list), "report.strategies must be a list"
    assert len(report["strategies"]) == len(_SMOKE_IR_PATHS), (
        f"expected {len(_SMOKE_IR_PATHS)} strategy records, got {len(report['strategies'])}"
    )

    # 3. Per-strategy record shape. Every field the dataclass declares
    #    must be present so consumers can rely on a stable schema.
    expected_fields = {
        "ir_path",
        "strategy_name",
        "strategy_version",
        "symbols",
        "timeframe",
        "bars_processed",
        "trade_count",
        "total_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
        "final_equity",
        "blotter_sha256",
    }
    for record in report["strategies"]:
        missing = expected_fields - set(record.keys())
        assert not missing, f"strategy record missing fields: {missing}"
        # Decimal-typed metrics must be strings for byte determinism.
        for decimal_field in (
            "total_return_pct",
            "sharpe_ratio",
            "max_drawdown_pct",
            "win_rate",
            "profit_factor",
            "final_equity",
        ):
            assert isinstance(record[decimal_field], str), (
                f"{decimal_field} must be a Decimal-as-string for byte "
                f"determinism; got {type(record[decimal_field]).__name__}"
            )
        # Blotter SHA must look like a 64-char hex digest.
        sha = record["blotter_sha256"]
        assert isinstance(sha, str) and len(sha) == 64, (
            f"blotter_sha256 must be a 64-char hex string; got {sha!r}"
        )
        int(sha, 16)  # raises ValueError if non-hex

    # 4. Markdown table on stdout. Verify the header row + one row per
    #    strategy + the eight metric column names so a regression in
    #    the printed format is caught.
    for header in (
        "| Strategy",
        "| Trades",
        "| Return %",
        "| Sharpe",
        "| MaxDD %",
        "| Win Rate",
        "| Profit Factor",
        "| Final Equity",
        "| Blotter SHA",
    ):
        assert header in stdout, (
            f"stdout missing Markdown header column {header!r}; got:\n{stdout!r}"
        )
    # One header row + one separator row + one data row per strategy.
    expected_pipe_lines = 2 + len(_SMOKE_IR_PATHS)
    pipe_lines = [line for line in stdout.splitlines() if line.startswith("|")]
    assert len(pipe_lines) == expected_pipe_lines, (
        f"expected {expected_pipe_lines} Markdown table lines on stdout, "
        f"got {len(pipe_lines)}; full stdout:\n{stdout}"
    )

    # 5. Determinism: re-run with same args, same output path, byte
    #    compare. The sha256 hash gives the failure message a clean
    #    one-line diff hint when this regresses.
    first_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    first_per_strategy_shas = [r["blotter_sha256"] for r in report["strategies"]]
    output_path.unlink()
    exit_code_2, _stdout_2, _stderr_2 = _run_cli(output_path)
    assert exit_code_2 == 0, "second invocation must also succeed"
    second_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    assert first_hash == second_hash, (
        f"determinism violation: report hashes differ between runs\n"
        f"  first  = {first_hash}\n"
        f"  second = {second_hash}\n"
        "Multi-strategy CLI contract: same IRs + same window + same "
        "seed = byte-identical JSON report."
    )
    second_report = json.loads(output_path.read_text(encoding="utf-8"))
    second_per_strategy_shas = [r["blotter_sha256"] for r in second_report["strategies"]]
    assert first_per_strategy_shas == second_per_strategy_shas, (
        "per-strategy blotter SHAs differ between runs; the executor "
        "is no longer deterministic for at least one IR. Check the "
        "synthetic provider seed plumbing and the paper broker fill "
        "ordering."
    )
