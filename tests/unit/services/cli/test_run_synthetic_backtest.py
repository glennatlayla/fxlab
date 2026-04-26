"""
Smoke tests for ``services.cli.run_synthetic_backtest`` (M3.X1 CLI).

The single end-to-end smoke test exercises the production code path
against the canonical Lien double-Bollinger IR over a 60-day window
with seed=42, asserts:

    1. The CLI returns exit code 0.
    2. The output JSON has the expected top-level shape with a
       ``trades`` key whose value is a list.
    3. Re-running the CLI with the same arguments produces a
       byte-identical output file (the CLAUDE.md §0 determinism
       contract).

The smoke test must finish in <10s -- this is part of the M3.X1
acceptance contract (the orchestrator runs it as a pre-merge gate).
The 60-day window combined with the Lien strategy's 4h primary
timeframe yields ~360 bars per FX pair. With four supported symbols
in the universe this is ~1,440 bars -- well within the budget.

Dependencies:
    - :mod:`services.cli.run_synthetic_backtest` -- module under test.
    - :mod:`pytest` for ``tmp_path`` and assertion helpers.

Does NOT:
    - Touch the network, an external broker, or any database.
    - Mock any sibling-tranche file. The whole purpose of M3.X1 is
      that the synthetic provider + paper broker are real and
      deterministic; mocking them would defeat the smoke test.
"""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from services.cli import run_synthetic_backtest as cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: Project-root-relative path to the canonical Lien IR. The smoke
#: test runs against the M3.X1 spec's exact strategy file so a
#: future operator can reproduce the run from the workplan as-is.
_LIEN_IR_PATH: Path = (
    Path(__file__).resolve().parents[4]
    / "Strategy Repo"
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_DoubleBollinger_TrendZone.strategy_ir.json"
)

#: Window the CLI will replay. Sized to ~60 calendar days (about
#: 360 bars at the Lien strategy's 4h timeframe) so the test finishes
#: comfortably under the 10-second budget while still exercising
#: enough bars for indicator warm-up.
_START_DATE: str = "2026-01-01"
_END_DATE: str = "2026-03-02"
_SEED: int = 42


def _run_cli(output_path: Path) -> tuple[int, str, str]:
    """
    Invoke :func:`cli.main` with the smoke-test argument set and
    capture exit code + stdout + stderr.

    Returns:
        ``(exit_code, stdout, stderr)``.
    """
    argv = [
        "--ir",
        str(_LIEN_IR_PATH),
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
# Smoke test -- exit-code + blotter shape + determinism
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_smoke_against_lien_ir_produces_deterministic_blotter(tmp_path: Path) -> None:
    """
    End-to-end exercise of the M3.X1 CLI.

    Asserts:
        - The IR fixture exists (otherwise the test is meaningless).
        - First invocation returns exit 0.
        - Output JSON has the expected top-level keys: ``run``,
          ``trades`` (list), ``open_positions`` (list),
          ``ending_balance`` (string).
        - Stdout contains all four summary metric names so a regression
          in the printed output is caught.
        - Second invocation with the SAME arguments produces a
          byte-identical output file (SHA-256 equality). This is the
          CLAUDE.md §0 determinism contract for the synthetic-data
          path.
    """
    assert _LIEN_IR_PATH.exists(), (
        f"Lien IR fixture not found at {_LIEN_IR_PATH}; the M3.X1 smoke "
        "test cannot run without it. The repo includes this file under "
        "Strategy Repo/; if it is missing, restore from git history."
    )

    output_path = tmp_path / "blotter.json"
    exit_code, stdout, _stderr = _run_cli(output_path)

    # 1. Exit code: must be 0 for downstream tooling (CI, the
    #    orchestrator's verification step) to consider the run
    #    successful.
    assert exit_code == 0, (
        f"CLI exited with {exit_code}; stdout={stdout!r}; "
        f"see captured stderr in test failure for context"
    )

    # 2. Output file structure.
    assert output_path.exists(), "CLI did not produce the --output file"
    blotter = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(blotter, dict), "blotter must be a JSON object"
    for key in ("run", "trades", "open_positions", "ending_balance"):
        assert key in blotter, f"blotter missing top-level key {key!r}"

    assert isinstance(blotter["trades"], list), "blotter.trades must be a list"
    assert isinstance(blotter["open_positions"], list), "blotter.open_positions must be a list"
    assert isinstance(blotter["ending_balance"], str), (
        "ending_balance must be a Decimal-as-string for byte determinism"
    )

    # Run config echoed back so an operator inspecting the blotter
    # later can reproduce the exact arguments. The seed must round-trip
    # as an int (not a string) so JSON consumers can compare cleanly.
    run_block = blotter["run"]
    assert run_block["seed"] == _SEED
    assert run_block["start"] == _START_DATE
    assert run_block["end"] == _END_DATE

    # 3. Stdout must surface the four summary metrics.
    for metric in ("total_trades=", "win_rate=", "total_return_pct=", "sharpe="):
        assert metric in stdout, f"stdout missing summary metric {metric!r}; got:\n{stdout!r}"

    # 4. Determinism: re-run with same args, same output path, byte
    #    compare. The sha256 hash gives the failure message a clean
    #    one-line diff hint when this regresses.
    first_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    output_path.unlink()
    exit_code_2, _stdout_2, _stderr_2 = _run_cli(output_path)
    assert exit_code_2 == 0, "second invocation must also succeed"
    second_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    assert first_hash == second_hash, (
        f"determinism violation: blotter hashes differ between runs\n"
        f"  first  = {first_hash}\n"
        f"  second = {second_hash}\n"
        "M3.X1 contract: same IR + same window + same seed = "
        "byte-identical blotter."
    )
