"""
Unit tests for ``scripts/smoke_health_eval.py`` — the install-smoke
health evaluator extracted from the Makefile's inline ``python3 -c``.

Context
-------
During the 2026-04-20 minitux failure, the fxlab-cadvisor container
was exit-2 restart-looping because ``--disable_metrics=accelerator,...``
contained an unknown metric name (Nvidia GPU metrics were removed in
cAdvisor v0.47). The compose restart policy kept it looping.

``make install-smoke`` ran on minitux but did NOT catch this. The
embedded health evaluator classified a service as healthy when
``Health`` was one of ``{'healthy', ''}`` — ignoring ``State``
entirely. A container in ``State=restarting`` between crashloops
(which is how cadvisor's failure appears in ``docker compose ps
--format json``) reports ``Health=''`` and so slipped through.

This module locks the contract for the extracted evaluator:

  - State-based classification (not Health-only).
  - ``State=restarting`` is terminal-fail (RESTART_LOOPING).
  - ``State=running`` + ``Health=unhealthy`` is terminal-fail.
  - ``State=running`` + ``Health=starting`` is transient (caller
    should keep waiting, not abort).
  - ``State=running`` + ``Health=''`` (no healthcheck defined) is
    healthy — not every service declares a healthcheck.
  - Zero services in the input is a fail state (empty stack).

The module is invoked as a CLI by the Makefile and is also import-
able for unit testing. The tests exercise the import path (no
subprocess spawn) for speed.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Module loader (keeps this test file standalone — no conftest coupling)
# ---------------------------------------------------------------------------

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_MODULE_PATH: Path = _PROJECT_ROOT / "scripts" / "smoke_health_eval.py"


def _load_module() -> Any:
    """Import ``scripts/smoke_health_eval.py`` by absolute path.

    Using importlib rather than a package-relative import keeps this
    test independent of sys.path tweaks in the project root conftest —
    the test file can be run in isolation with ``pytest -p no:cacheprovider
    --noconftest tests/unit/test_smoke_health_eval.py`` for fast
    iteration during development.
    """
    if not _MODULE_PATH.is_file():
        pytest.fail(f"smoke_health_eval.py not found at {_MODULE_PATH}")
    spec = importlib.util.spec_from_file_location("smoke_health_eval", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_health_eval"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod() -> Any:
    """Load the evaluator module once per test module."""
    return _load_module()


# ---------------------------------------------------------------------------
# Canned docker-compose ps --format json fixtures
# ---------------------------------------------------------------------------
#
# Each fixture returns the list of dicts the evaluator consumes —
# equivalent to iterating over ``docker compose ps --format json``
# (which emits one JSON object per line, NOT a JSON array).
# ---------------------------------------------------------------------------


def _svc(
    name: str,
    *,
    state: str,
    health: str = "",
    exit_code: int = 0,
    status: str | None = None,
) -> dict[str, Any]:
    """Build a compose-ps service dict."""
    return {
        "Service": name,
        "Name": f"fxlab-{name}",
        "State": state,
        "Health": health,
        "ExitCode": exit_code,
        "Status": status or f"{state} — synthetic fixture",
    }


# ---------------------------------------------------------------------------
# Exit code contract
# ---------------------------------------------------------------------------
#
# The Makefile poll loop interprets the evaluator's exit codes:
#   0 — all services healthy; stop waiting, install-smoke succeeds.
#   1 — at least one service is terminally failed; stop waiting,
#       install-smoke fails fast.
#   2 — at least one service is transiently unhealthy (starting,
#       still within healthcheck warmup); keep waiting.
#
# Zero services in the input is exit 1 (fail fast) — an empty stack
# cannot be "healthy", and the 2026-04-16 postmortem on minitux
# noted that "zero services" was being reported as success when the
# daemon had died mid-run.
# ---------------------------------------------------------------------------


EXIT_HEALTHY = 0
EXIT_FAILED = 1
EXIT_WAITING = 2


# ---------------------------------------------------------------------------
# Tests — classification
# ---------------------------------------------------------------------------


def test_classify_running_and_healthy_is_healthy(mod: Any) -> None:
    """State=running + Health=healthy is the unambiguous success case."""
    result = mod.classify(_svc("api", state="running", health="healthy"))
    assert result.status == mod.ServiceStatus.HEALTHY
    assert not result.terminal
    assert result.reason  # non-empty human-readable reason


def test_classify_running_and_starting_is_waiting(mod: Any) -> None:
    """Health=starting means we should keep waiting, not fail."""
    result = mod.classify(_svc("api", state="running", health="starting"))
    assert result.status == mod.ServiceStatus.STARTING
    assert not result.terminal


def test_classify_running_and_unhealthy_is_terminal_fail(mod: Any) -> None:
    """Health=unhealthy after start_period+retries is terminal.

    The container is still running, but compose's healthcheck has
    decided it will not become healthy. Fail fast — further waiting
    is pointless.
    """
    result = mod.classify(_svc("api", state="running", health="unhealthy"))
    assert result.status == mod.ServiceStatus.UNHEALTHY
    assert result.terminal


def test_classify_running_no_healthcheck_is_healthy(mod: Any) -> None:
    """State=running + Health='' means the service declared no healthcheck.

    We cannot fail it for that — not every service defines a healthcheck
    (the web tier's nginx, for instance). Treat as healthy.
    """
    result = mod.classify(_svc("oneshot", state="running", health=""))
    assert result.status == mod.ServiceStatus.HEALTHY
    assert not result.terminal


def test_classify_restarting_is_terminal_fail(mod: Any) -> None:
    """State=restarting is the cAdvisor crashloop signature.

    This is the SPECIFIC case the pre-remediation Makefile evaluator
    missed. Health is empty during restart-loop gaps, so a
    Health-only check classified restart-looping as healthy.

    ``terminal=True`` means the Makefile poll loop should STOP
    waiting (exit 1) rather than time out after SMOKE_TIMEOUT seconds.
    """
    result = mod.classify(_svc("cadvisor", state="restarting", health=""))
    assert result.status == mod.ServiceStatus.RESTART_LOOPING
    assert result.terminal
    assert "restart" in result.reason.lower()


def test_classify_exited_nonzero_is_exhausted(mod: Any) -> None:
    """State=exited + ExitCode!=0 means the restart budget was exhausted.

    Under the compose ``restart: on-failure:3`` policy this is the
    terminal state. Under ``restart: unless-stopped`` it generally
    cycles to restarting, but we still classify as exhausted if
    we see the snapshot.
    """
    result = mod.classify(_svc("api", state="exited", exit_code=3))
    assert result.status == mod.ServiceStatus.EXHAUSTED
    assert result.terminal
    assert "3" in result.reason  # exit code surfaced in reason


def test_classify_exited_zero_is_terminal_fail(mod: Any) -> None:
    """State=exited + ExitCode=0 is still a failure for long-running services.

    A service that was expected to stay up but exited cleanly is a
    bug (usually an entrypoint that read malformed env and returned
    0 rather than raising). Fail fast.
    """
    result = mod.classify(_svc("api", state="exited", exit_code=0))
    assert result.status == mod.ServiceStatus.EXITED_UNEXPECTEDLY
    assert result.terminal


def test_classify_created_is_blocked(mod: Any) -> None:
    """State=created means depends_on chain is stuck.

    No container that reaches 'created' and sits there is healthy —
    it's waiting on a dependency that never became ready. Surface
    as a terminal fail so the operator sees the blocking chain.
    """
    result = mod.classify(_svc("web", state="created"))
    assert result.status == mod.ServiceStatus.BLOCKED
    assert result.terminal


def test_classify_dead_is_terminal_fail(mod: Any) -> None:
    """State=dead is a docker daemon-level failure."""
    result = mod.classify(_svc("api", state="dead"))
    assert result.status == mod.ServiceStatus.DEAD
    assert result.terminal


def test_classify_unknown_state_is_terminal_fail(mod: Any) -> None:
    """Unknown State values are treated as terminal-fail, not swallowed.

    The 2026-04-16 minitux postmortem specifically called out 'silent
    failure modes' — classifying as STARTING-by-default would re-
    introduce that bug. Fail loud when we don't recognise a state.
    """
    result = mod.classify(_svc("api", state="paused"))
    assert result.terminal
    assert "paused" in result.reason.lower()


# ---------------------------------------------------------------------------
# Tests — overall verdict
# ---------------------------------------------------------------------------


def test_overall_verdict_all_healthy_exits_zero(mod: Any) -> None:
    services = [
        _svc("api", state="running", health="healthy"),
        _svc("redis", state="running", health="healthy"),
        _svc("postgres", state="running", health="healthy"),
    ]
    verdict = mod.overall_verdict(services)
    assert verdict.exit_code == EXIT_HEALTHY
    assert verdict.summary  # non-empty


def test_overall_verdict_any_starting_exits_waiting(mod: Any) -> None:
    """If every service is healthy-or-starting, the caller should wait."""
    services = [
        _svc("api", state="running", health="starting"),
        _svc("redis", state="running", health="healthy"),
    ]
    verdict = mod.overall_verdict(services)
    assert verdict.exit_code == EXIT_WAITING


def test_overall_verdict_any_terminal_exits_failed(mod: Any) -> None:
    """One terminal failure wins over any number of starting/healthy."""
    services = [
        _svc("cadvisor", state="restarting"),
        _svc("api", state="running", health="starting"),
        _svc("redis", state="running", health="healthy"),
    ]
    verdict = mod.overall_verdict(services)
    assert verdict.exit_code == EXIT_FAILED
    assert "cadvisor" in verdict.summary


def test_overall_verdict_cadvisor_restart_loop_wins(mod: Any) -> None:
    """Regression guard for the 2026-04-20 minitux failure.

    A stack where every core service is healthy and ONLY cadvisor is
    restart-looping must still exit FAILED — the cadvisor flag bug
    MUST not be silently ignored because it's 'only observability'.
    """
    services = [
        _svc("api", state="running", health="healthy"),
        _svc("redis", state="running", health="healthy"),
        _svc("postgres", state="running", health="healthy"),
        _svc("web", state="running", health="healthy"),
        _svc("nginx", state="running", health="healthy"),
        _svc("prometheus", state="running", health="healthy"),
        _svc("node-exporter", state="running", health="healthy"),
        _svc("cadvisor", state="restarting"),  # ← the bug
    ]
    verdict = mod.overall_verdict(services)
    assert verdict.exit_code == EXIT_FAILED
    assert "cadvisor" in verdict.summary
    # The verdict summary must name the failure class so a minitux
    # operator can fix it without re-running with more verbosity.
    assert "restart" in verdict.summary.lower()


def test_overall_verdict_empty_stack_exits_failed(mod: Any) -> None:
    """Zero services is a fail state — empty stack cannot be healthy.

    The 2026-04-16 minitux postmortem noted install-smoke declaring
    'All services healthy after 0s' when the daemon had died. That
    must never happen again.
    """
    verdict = mod.overall_verdict([])
    assert verdict.exit_code == EXIT_FAILED
    assert "no services" in verdict.summary.lower() or "empty" in verdict.summary.lower()


# ---------------------------------------------------------------------------
# Tests — NDJSON input parser
# ---------------------------------------------------------------------------
#
# ``docker compose ps --format json`` emits one JSON object per line,
# NOT a JSON array. The parser has to handle that, plus the blank
# lines compose sometimes intersperses.
# ---------------------------------------------------------------------------


def test_parse_ndjson_handles_one_object_per_line(mod: Any) -> None:
    text = "\n".join(
        [
            json.dumps(_svc("a", state="running", health="healthy")),
            json.dumps(_svc("b", state="running", health="healthy")),
        ]
    )
    parsed = mod.parse_ps_ndjson(text)
    assert len(parsed) == 2
    assert {s["Service"] for s in parsed} == {"a", "b"}


def test_parse_ndjson_skips_blank_lines_and_whitespace(mod: Any) -> None:
    text = (
        "\n\n"
        + json.dumps(_svc("a", state="running", health="healthy"))
        + "\n   \n"
        + json.dumps(_svc("b", state="running", health="healthy"))
        + "\n\n"
    )
    parsed = mod.parse_ps_ndjson(text)
    assert len(parsed) == 2


def test_parse_ndjson_raises_on_malformed_line(mod: Any) -> None:
    """A malformed JSON line must raise, not be silently skipped.

    Silent skip is how ``install-smoke`` would have reported zero
    services when compose's output changed format — exactly the kind
    of 'it just worked' behaviour the 2026-04-16 postmortem flagged.
    """
    text = (
        json.dumps(_svc("a", state="running", health="healthy"))
        + "\nnot-json\n"
        + json.dumps(_svc("b", state="running", health="healthy"))
    )
    with pytest.raises(ValueError, match="line 2"):
        mod.parse_ps_ndjson(text)


def test_parse_ndjson_empty_input_returns_empty_list(mod: Any) -> None:
    assert mod.parse_ps_ndjson("") == []
    assert mod.parse_ps_ndjson("\n\n   \n") == []


# ---------------------------------------------------------------------------
# Tests — log pattern scanner
# ---------------------------------------------------------------------------
#
# The 2026-04-20 cadvisor failure left a specific stderr fingerprint
# ('Usage of cadvisor:' header followed by the flag table). A scanner
# that recognises this signature is a cheap second-line-of-defence
# for any image whose flag parser dumps usage on error — cadvisor
# today, potentially others tomorrow.
# ---------------------------------------------------------------------------


USAGE_DUMP_SAMPLE = """
Usage of cadvisor:
  -add_dir_header
        If true, adds the file directory to the header of the log messages
  -alsologtostderr
        log to standard error as well as files (no effect when -logtostderr=true)
  -port int
        port to listen (default 8080)
"""


def test_log_scanner_detects_cadvisor_usage_dump(mod: Any) -> None:
    """The specific fingerprint of cAdvisor's flag-parse failure."""
    hits = mod.scan_logs_for_flag_parse_failure(USAGE_DUMP_SAMPLE)
    assert hits, "scanner must detect 'Usage of cadvisor:' signature"


def test_log_scanner_detects_generic_go_flag_error(mod: Any) -> None:
    """Go's stdlib flag package emits a characteristic error line."""
    sample = "flag provided but not defined: -accelerator\nUsage of cadvisor:\n"
    hits = mod.scan_logs_for_flag_parse_failure(sample)
    assert hits
    # The specific offending line is surfaced so the operator can act.
    assert any("accelerator" in h for h in hits)


def test_log_scanner_ignores_normal_startup_logs(mod: Any) -> None:
    sample = """
    I0420 12:00:00.000000 cadvisor.go:219] Starting cAdvisor version: v0.49.1
    I0420 12:00:00.100000 manager.go:172] cAdvisor running in container: "/"
    I0420 12:00:00.200000 manager.go:307] Starting recovery of all containers
    """
    assert not mod.scan_logs_for_flag_parse_failure(sample)


def test_log_scanner_ignores_legitimate_help_word(mod: Any) -> None:
    """Do not false-positive on the word 'usage' in structured log lines."""
    sample = '{"level":"INFO","msg":"CPU usage normal","ts":"2026-04-20T12:00:00Z"}'
    assert not mod.scan_logs_for_flag_parse_failure(sample)
