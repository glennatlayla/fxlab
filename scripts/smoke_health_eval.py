#!/usr/bin/env python3
"""
scripts/smoke_health_eval.py — install-smoke health evaluator.

Purpose
-------
Replace the inline ``python3 -c "..."`` one-liner that lived inside
the ``install-smoke`` target in the Makefile with a typed, documented,
unit-tested module.

Responsibilities
- Parse ``docker compose ps --format json`` output (NDJSON — one JSON
  object per line, NOT a JSON array) into a list of service dicts.
- Classify each service as one of: HEALTHY, STARTING, UNHEALTHY,
  RESTART_LOOPING, EXHAUSTED, EXITED_UNEXPECTEDLY, BLOCKED, DEAD,
  UNKNOWN — using both State and Health, because Health alone is
  insufficient (a restart-looping container reports Health='' between
  attempts, which a Health-only check silently treated as healthy).
- Compute an overall verdict and exit code suitable for driving a
  Makefile poll loop:

      exit 0 — every service is HEALTHY; the stack is up.
      exit 1 — at least one service is in a TERMINAL failure state;
               the caller should stop waiting and fail the install.
      exit 2 — no terminal failures, but at least one service is
               STARTING; the caller should wait and retry.

- Provide a log-pattern scanner for the specific failure fingerprint
  (cAdvisor "Usage of cadvisor:" dump; Go stdlib "flag provided but
  not defined" error) that the 2026-04-20 minitux incident produced.
  Catching this signature at smoke-time prevents shipping an image
  with an invalid flag set — a second-line-of-defence beyond the
  YAML hygiene contract.

Does NOT
- Launch containers or talk to the Docker daemon; it only consumes
  the JSON output the caller (install.sh / Makefile / CI) pipes in.
  Keeping this tool daemon-agnostic is what makes it unit-testable.
- Decide retry/backoff policy; that stays in the Makefile poll loop.

Dependencies
- Python stdlib only (json, re, sys, dataclasses, enum, typing).
  No third-party packages so this runs unmodified on minitux,
  macOS dev, and the Azure VM target.

Error conditions
- ``parse_ps_ndjson`` raises ValueError for malformed lines —
  silent-skip would reintroduce the exact 'it just worked' failure
  mode the 2026-04-16 install-smoke postmortem called out.
- ``classify`` never raises; unknown States fall through to
  UNKNOWN → terminal=True, so nothing is silently swallowed.

Example (CLI)
-------------
::

    $ docker compose -f docker-compose.prod.yml ps --format json \\
        | python3 scripts/smoke_health_eval.py poll
    [smoke-eval] HEALTHY      api             running (healthy)
    [smoke-eval] HEALTHY      redis           running (healthy)
    [smoke-eval] RESTART_LOOP cadvisor        restarting
    [smoke-eval] verdict: FAILED
    $ echo $?
    1

Example (import)
----------------
::

    from smoke_health_eval import classify, overall_verdict, ServiceStatus
    result = classify({"Service": "api", "State": "running",
                       "Health": "healthy", "ExitCode": 0})
    assert result.status == ServiceStatus.HEALTHY
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Exit code constants — contract with the Makefile poll loop.
# ---------------------------------------------------------------------------

#: All services healthy — stop polling, install-smoke succeeds.
EXIT_HEALTHY: int = 0

#: At least one service is in a terminal failure state — stop polling
#: and fail the install. Further waiting will not improve outcome.
EXIT_FAILED: int = 1

#: No terminal failures, but at least one service is still STARTING.
#: Caller should sleep and re-invoke. If the smoke-timeout elapses
#: while we are still returning 2, the caller treats timeout as fail.
EXIT_WAITING: int = 2


# ---------------------------------------------------------------------------
# Classification taxonomy
# ---------------------------------------------------------------------------


class ServiceStatus(str, Enum):
    """Single-service classification.

    Inherits from str so status values serialise cleanly when the
    verdict is emitted as machine-readable lines for downstream tools.
    """

    #: Running and healthy (or running with no healthcheck declared).
    HEALTHY = "HEALTHY"

    #: Running, Health='starting' — still within start_period/retries.
    #: NOT terminal: caller should wait.
    STARTING = "STARTING"

    #: Running but Health='unhealthy' — healthcheck has decided it
    #: will not recover. Terminal.
    UNHEALTHY = "UNHEALTHY"

    #: State='restarting' — crashloop between attempts. The 2026-04-20
    #: cAdvisor failure mode. Terminal.
    RESTART_LOOPING = "RESTART_LOOPING"

    #: State='exited' with non-zero exit code — restart budget
    #: exhausted (under on-failure:N) or intentional exit with error.
    EXHAUSTED = "EXHAUSTED"

    #: State='exited' with exit code 0 — the service stopped cleanly
    #: when it was expected to stay up. Treated as terminal failure
    #: for long-running services (which all fxlab services are).
    EXITED_UNEXPECTEDLY = "EXITED_UNEXPECTEDLY"

    #: State='created' — the container was created but never started
    #: because its depends_on chain never resolved.
    BLOCKED = "BLOCKED"

    #: State='dead' — docker-daemon-level failure.
    DEAD = "DEAD"

    #: State is something we did not expect. Terminal by default —
    #: silent passthrough on unknown states is precisely how the
    #: 2026-04-16 postmortem bug manifested.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClassificationResult:
    """Per-service classification outcome."""

    status: ServiceStatus
    #: True if the caller should abort polling (failure or success
    #: that definitely will not change). False only for STARTING —
    #: the sole "wait longer" state.
    terminal: bool
    #: Short human-readable reason that appears in operator output.
    reason: str


@dataclass(frozen=True)
class ServiceVerdict:
    """One line in the overall verdict: service + classification."""

    name: str
    status: ServiceStatus
    reason: str


@dataclass(frozen=True)
class OverallVerdict:
    """Aggregate verdict over the whole compose ps snapshot."""

    exit_code: int
    summary: str
    services: list[ServiceVerdict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# State → classification table
# ---------------------------------------------------------------------------
#
# Pure data. The ``classify()`` function below is the only code that
# mutates classification outcomes; the table here lets us reason
# about coverage without chasing control flow.
# ---------------------------------------------------------------------------


def classify(service: dict[str, Any]) -> ClassificationResult:
    """Classify a single ``docker compose ps`` service dict.

    Args:
        service: one JSON object from ``docker compose ps --format json``.
            Expected keys: ``State`` (str), ``Health`` (str — may be
            empty if the service declared no healthcheck),
            ``ExitCode`` (int), ``Service`` (str name).

    Returns:
        ClassificationResult with ``status``, ``terminal``, and a
        short ``reason`` string that surfaces in operator output.

    Notes:
        This function never raises — unknown/missing fields fall
        through to ``ServiceStatus.UNKNOWN``.

    Example:
        >>> classify({"Service": "api", "State": "running",
        ...           "Health": "healthy", "ExitCode": 0}).status
        <ServiceStatus.HEALTHY: 'HEALTHY'>
    """
    state = str(service.get("State", "")).lower()
    health = str(service.get("Health", "")).lower()
    exit_code = service.get("ExitCode", 0)
    # Coerce exit_code to int defensively; compose has emitted it as
    # either a number or a stringified number across versions.
    try:
        exit_code_int = int(exit_code)
    except (TypeError, ValueError):
        exit_code_int = -1

    if state == "running":
        if health in ("", "healthy"):
            # Empty health with State=running means the service did
            # not declare a healthcheck — we cannot fail it for that.
            reason = (
                "running (healthy)" if health == "healthy" else "running (no healthcheck declared)"
            )
            return ClassificationResult(
                status=ServiceStatus.HEALTHY,
                terminal=False,
                reason=reason,
            )
        if health == "starting":
            return ClassificationResult(
                status=ServiceStatus.STARTING,
                terminal=False,
                reason="running (health: starting)",
            )
        if health == "unhealthy":
            return ClassificationResult(
                status=ServiceStatus.UNHEALTHY,
                terminal=True,
                reason="running but healthcheck failed (unhealthy)",
            )
        # Any other Health value is an unexpected compose emission.
        return ClassificationResult(
            status=ServiceStatus.UNKNOWN,
            terminal=True,
            reason=f"running with unknown Health={health!r}",
        )

    if state == "restarting":
        return ClassificationResult(
            status=ServiceStatus.RESTART_LOOPING,
            terminal=True,
            reason="container is restart-looping (check logs for flag-parse failure)",
        )

    if state == "exited":
        if exit_code_int == 0:
            return ClassificationResult(
                status=ServiceStatus.EXITED_UNEXPECTEDLY,
                terminal=True,
                reason="exited cleanly (exit 0) — expected to stay up",
            )
        return ClassificationResult(
            status=ServiceStatus.EXHAUSTED,
            terminal=True,
            reason=f"exited with code {exit_code_int} (restart budget exhausted)",
        )

    if state == "created":
        return ClassificationResult(
            status=ServiceStatus.BLOCKED,
            terminal=True,
            reason="created but never started (depends_on chain blocked)",
        )

    if state == "dead":
        return ClassificationResult(
            status=ServiceStatus.DEAD,
            terminal=True,
            reason="dead (docker daemon marked container dead)",
        )

    return ClassificationResult(
        status=ServiceStatus.UNKNOWN,
        terminal=True,
        reason=f"unknown State={state!r}",
    )


# ---------------------------------------------------------------------------
# Aggregate verdict
# ---------------------------------------------------------------------------


def overall_verdict(services: list[dict[str, Any]]) -> OverallVerdict:
    """Aggregate classifications into a single exit-code/summary pair.

    Args:
        services: list of ``docker compose ps --format json`` objects
            (one per service).

    Returns:
        OverallVerdict with ``exit_code`` in {0, 1, 2}, a human-
        readable ``summary`` string, and per-service details.

    Decision table:
        - Empty services list → ``EXIT_FAILED`` (an empty stack cannot
          be healthy; specifically the 2026-04-16 minitux bug).
        - Any service is terminal-failed → ``EXIT_FAILED``.
        - Else, any service is STARTING → ``EXIT_WAITING``.
        - Else → ``EXIT_HEALTHY``.
    """
    if not services:
        return OverallVerdict(
            exit_code=EXIT_FAILED,
            summary=(
                "FAILED — compose reports no services running. "
                "An empty stack is never healthy; this usually means "
                "'docker compose up' failed silently or the daemon died."
            ),
            services=[],
        )

    verdicts: list[ServiceVerdict] = []
    any_terminal = False
    any_starting = False
    terminal_names: list[str] = []

    for svc in services:
        name = str(svc.get("Service") or svc.get("Name") or "<unknown>")
        result = classify(svc)
        verdicts.append(
            ServiceVerdict(
                name=name,
                status=result.status,
                reason=result.reason,
            )
        )
        if result.terminal and result.status != ServiceStatus.HEALTHY:
            any_terminal = True
            terminal_names.append(f"{name} [{result.status.value}: {result.reason}]")
        if result.status == ServiceStatus.STARTING:
            any_starting = True

    if any_terminal:
        return OverallVerdict(
            exit_code=EXIT_FAILED,
            summary=(
                "FAILED — "
                + str(len(terminal_names))
                + " service(s) in terminal failure state: "
                + "; ".join(terminal_names)
            ),
            services=verdicts,
        )

    if any_starting:
        starting_names = [v.name for v in verdicts if v.status == ServiceStatus.STARTING]
        return OverallVerdict(
            exit_code=EXIT_WAITING,
            summary=(
                "WAITING — "
                + str(len(starting_names))
                + " service(s) still starting: "
                + ", ".join(starting_names)
            ),
            services=verdicts,
        )

    return OverallVerdict(
        exit_code=EXIT_HEALTHY,
        summary=f"HEALTHY — all {len(verdicts)} services healthy",
        services=verdicts,
    )


# ---------------------------------------------------------------------------
# NDJSON parser
# ---------------------------------------------------------------------------


def parse_ps_ndjson(text: str) -> list[dict[str, Any]]:
    """Parse ``docker compose ps --format json`` output into dicts.

    Compose emits one JSON object per line (NDJSON), not a JSON array.
    Blank lines and pure-whitespace lines are ignored; any line that
    is non-empty but not valid JSON raises ``ValueError`` with the
    1-indexed line number so the operator can pinpoint it.

    Args:
        text: the raw output of ``docker compose ps --format json``.

    Returns:
        List of parsed service dicts in the order they appeared.

    Raises:
        ValueError: if any non-blank line is not valid JSON. The
        message includes the line number ("line N").
    """
    results: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"malformed JSON on line {line_no}: {exc.msg} (content: {stripped!r})"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"expected JSON object on line {line_no}, got {type(parsed).__name__}")
        results.append(parsed)
    return results


# ---------------------------------------------------------------------------
# Log pattern scanner
# ---------------------------------------------------------------------------
#
# Matches two fingerprints that the 2026-04-20 minitux cadvisor
# failure emitted:
#
#   1. "Usage of <binary>:" — Go's flag package prints this header
#      just before dumping the flag table on parse error or -h.
#   2. "flag provided but not defined: -<name>" — the specific
#      error line Go's flag package emits for unknown flags, and
#      the closely related "invalid value ... for flag -<name>:"
#      for reject-at-parse cases like our accelerator bug.
#
# Both are anchored to per-line regex so we do not false-positive
# on the word 'usage' appearing in structured log payloads.
# ---------------------------------------------------------------------------

_USAGE_HEADER_RE: re.Pattern[str] = re.compile(r"^Usage of [A-Za-z0-9_\-.]+:\s*$")
_FLAG_NOT_DEFINED_RE: re.Pattern[str] = re.compile(r"^flag provided but not defined:\s*-\S+")
_INVALID_VALUE_RE: re.Pattern[str] = re.compile(r"^invalid value .* for flag -\S+")


def scan_logs_for_flag_parse_failure(log_text: str) -> list[str]:
    """Return matching lines from ``log_text`` that indicate a flag-parse failure.

    Args:
        log_text: stdout+stderr concatenation from a container's
            ``docker logs`` output.

    Returns:
        List of matching lines (already stripped). Empty list if
        no match. Callers treat a non-empty list as a terminal
        failure because a container that prints a flag-parse error
        is about to exit non-zero and restart-loop.

    Example:
        >>> scan_logs_for_flag_parse_failure(
        ...     "flag provided but not defined: -accelerator\\nUsage of cadvisor:\\n"
        ... )
        ['flag provided but not defined: -accelerator', 'Usage of cadvisor:']
    """
    matches: list[str] = []
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if (
            _USAGE_HEADER_RE.match(line)
            or _FLAG_NOT_DEFINED_RE.match(line)
            or _INVALID_VALUE_RE.match(line)
        ):
            matches.append(line)
    return matches


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


_LINE_FMT: str = "[smoke-eval] {status:<22} {name:<20} {reason}"


def _print_verdict(verdict: OverallVerdict, stream: Any = sys.stdout) -> None:
    """Emit human-readable verdict to ``stream``."""
    for svc in verdict.services:
        print(
            _LINE_FMT.format(
                status=svc.status.value,
                name=svc.name,
                reason=svc.reason,
            ),
            file=stream,
        )
    print(f"[smoke-eval] verdict: {verdict.summary}", file=stream)


def main(argv: list[str]) -> int:
    """CLI entrypoint.

    Subcommand:
        poll    Read ``docker compose ps --format json`` from stdin,
                emit classifications, and exit with EXIT_HEALTHY (0),
                EXIT_FAILED (1), or EXIT_WAITING (2) per the contract
                at the top of this module. This is the mode the
                Makefile poll loop calls.
        scan-logs
                Read container logs from stdin, exit 0 if no flag-
                parse failure signature is found, exit 1 otherwise.
                Offending lines are printed to stderr.

    Returns:
        Process exit code. Never raises on well-formed input.
    """
    if len(argv) < 2:
        print(
            "usage: smoke_health_eval.py {poll|scan-logs}",
            file=sys.stderr,
        )
        return 2  # EX_USAGE-ish; caller distinguishes from STARTING by message.

    subcmd = argv[1]

    if subcmd == "poll":
        text = sys.stdin.read()
        try:
            services = parse_ps_ndjson(text)
        except ValueError as exc:
            print(f"[smoke-eval] malformed input: {exc}", file=sys.stderr)
            return EXIT_FAILED
        verdict = overall_verdict(services)
        _print_verdict(verdict)
        return verdict.exit_code

    if subcmd == "scan-logs":
        text = sys.stdin.read()
        hits = scan_logs_for_flag_parse_failure(text)
        if hits:
            print(
                "[smoke-eval] flag-parse failure signature detected:",
                file=sys.stderr,
            )
            for line in hits:
                print(f"[smoke-eval]   {line}", file=sys.stderr)
            return EXIT_FAILED
        return EXIT_HEALTHY

    print(f"[smoke-eval] unknown subcommand: {subcmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
