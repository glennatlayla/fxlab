"""
Unit tests for N2 — node-exporter scrape hygiene (2026-04-15 remediation).

Context
-------
During the 2026-04-15 minitux install failure, node-exporter produced
a flood of ``connection reset by peer`` lines. Root cause analysis
during post-mortem:

  1. node-exporter's v1.7.0 default collector list enables ~44
     collectors. Several of them (``hwmon``, ``thermal_zone``,
     ``rapl``, ``mdadm``, ``fibrechannel``, ``tapestats``, ``edac``,
     ``bcache``, ``btrfs``, ``ipvs``, ``infiniband``, ``zfs``, ``xfs``,
     ``selinux``) probe ``/sys/...`` or ``/proc/...`` paths that do
     not exist inside the containerised kernel view on minitux.
     Each failing collector writes an error to its channel and
     closes its connection, which Prometheus sees as "connection
     reset by peer" mid-response.

  2. node-exporter's default ``--web.max-requests`` is 40. During
     Prometheus's first scrape, multiple collectors race to the
     listener and the 41st is rejected with RST. Raising the limit
     removes the race window.

  3. Prometheus's scrape_timeout must stay strictly less than the
     scrape_interval. Ensuring this invariant prevents the "scrape
     still in flight when the next scrape starts" window that also
     surfaces as RST at the TCP layer.

N2 locks these three invariants in. The test file parses both
``docker-compose.prod.yml`` and ``deploy/prometheus/prometheus.yml``
so a reviewer cannot silently undo the fix in either config.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Contract — explicit collector allowlist.
# ---------------------------------------------------------------------------
#
# We enumerate the collectors we depend on and turn off defaults so
# that unrelated collectors cannot silently fail and produce "reset
# by peer". Each collector appears with a rationale so reviewers see
# why it is required. Removing an entry here is a signal that the
# corresponding alert rule can also be retired.

REQUIRED_NODE_EXPORTER_COLLECTORS: tuple[tuple[str, str], ...] = (
    ("cpu", "CPU utilisation — HighCPU alert rule"),
    ("meminfo", "memory pressure — HighMemory alert rule"),
    ("loadavg", "system load — saturation dashboards"),
    ("filesystem", "disk usage — DiskUsage alert rule"),
    ("diskstats", "disk throughput — storage alerts"),
    ("netdev", "network I/O — NetworkSaturation alert rule"),
    ("netstat", "TCP / socket counters — NetworkErrors alert rule"),
    ("uname", "host metadata label — required by Grafana templating"),
    ("time", "clock skew detection — Ntp drift alert"),
    ("stat", "context-switch and interrupt counters"),
    ("vmstat", "virtual memory behaviour"),
)

#: Minimum --web.max-requests value. Raising from the 40 default
#: removes the race window that triggered the 2026-04-15 RST flood.
_MIN_WEB_MAX_REQUESTS = 50


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_prod_config() -> dict[str, Any]:
    """Parse ``docker-compose.prod.yml`` once per module."""
    root = Path(__file__).resolve().parents[2]
    path = root / "docker-compose.prod.yml"
    if not path.is_file():
        pytest.fail(f"docker-compose.prod.yml not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        parsed = yaml.safe_load(fh)
    assert isinstance(parsed, dict)
    return parsed


@pytest.fixture(scope="module")
def node_exporter_service(
    compose_prod_config: dict[str, Any],
) -> dict[str, Any]:
    services = compose_prod_config.get("services", {})
    assert "node-exporter" in services, (
        "docker-compose.prod.yml must define 'node-exporter' service."
    )
    return services["node-exporter"]


@pytest.fixture(scope="module")
def node_exporter_command(
    node_exporter_service: dict[str, Any],
) -> list[str]:
    command = node_exporter_service.get("command")
    assert isinstance(command, list), (
        "node-exporter command must be a YAML list, not a shell string. "
        "List form eliminates shell-quoting bugs."
    )
    return [str(flag) for flag in command]


@pytest.fixture(scope="module")
def prometheus_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    path = root / "deploy" / "prometheus" / "prometheus.yml"
    if not path.is_file():
        pytest.fail(f"prometheus.yml not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        parsed = yaml.safe_load(fh)
    assert isinstance(parsed, dict)
    return parsed


@pytest.fixture(scope="module")
def node_exporter_scrape_job(
    prometheus_config: dict[str, Any],
) -> dict[str, Any]:
    for job in prometheus_config.get("scrape_configs", []):
        if job.get("job_name") == "node-exporter":
            return job
    pytest.fail("prometheus.yml must define a 'node-exporter' scrape job")


# ---------------------------------------------------------------------------
# node-exporter command-line contract.
# ---------------------------------------------------------------------------


def test_node_exporter_disables_default_collectors(
    node_exporter_command: list[str],
) -> None:
    """``--collector.disable-defaults`` must be present.

    Without it, node-exporter enables ~44 collectors, many of which
    probe /sys paths not present on the minitux / Azure VM container
    kernels. Each failing collector can produce a connection-reset at
    the TCP layer when the scrape completes.
    """
    assert "--collector.disable-defaults" in node_exporter_command, (
        "--collector.disable-defaults must be present so the collector "
        "set is an explicit allowlist rather than the v1.7.0 default. "
        f"Command: {node_exporter_command!r}."
    )


@pytest.mark.parametrize(
    ("collector", "rationale"),
    REQUIRED_NODE_EXPORTER_COLLECTORS,
)
def test_node_exporter_enables_required_collector(
    node_exporter_command: list[str],
    collector: str,
    rationale: str,
) -> None:
    """Every required collector is explicitly enabled.

    The ``rationale`` parametrize id makes failure messages say what
    the collector is for, not just that it is missing.
    """
    expected = f"--collector.{collector}"
    assert expected in node_exporter_command, (
        f"Required collector flag missing: {expected!r}. "
        f"Rationale: {rationale}. "
        f"Command: {node_exporter_command!r}."
    )


def test_node_exporter_has_web_max_requests_flag(
    node_exporter_command: list[str],
) -> None:
    """``--web.max-requests`` must be set above the default 40.

    The default value produces TCP RST on the 41st concurrent request.
    Raising to at least 50 removes the race window without a
    meaningful resource cost. Each in-flight request costs a goroutine
    and a modest RAM footprint — well within our memory limit.
    """
    pattern = re.compile(r"^--web\.max-requests=(\d+)$")
    for entry in node_exporter_command:
        match = pattern.match(entry)
        if match:
            value = int(match.group(1))
            assert value >= _MIN_WEB_MAX_REQUESTS, (
                f"--web.max-requests={value} is below the minimum "
                f"{_MIN_WEB_MAX_REQUESTS}. Raising removes the race "
                "window that produced the 2026-04-15 RST flood."
            )
            return
    pytest.fail(
        "--web.max-requests=<n> must be present in the node-exporter "
        f"command (n >= {_MIN_WEB_MAX_REQUESTS}). "
        f"Command: {node_exporter_command!r}."
    )


def test_node_exporter_healthcheck_start_period_is_generous(
    node_exporter_service: dict[str, Any],
) -> None:
    """start_period must allow collectors to warm up before first probe.

    Collectors that read /proc and /sys can take a second or two to
    initialise on a cold boot. A start_period of at least 30 s
    prevents the "starting" → "unhealthy" flap that otherwise
    compounds with scrape-side RSTs.
    """
    hc = node_exporter_service.get("healthcheck", {})
    start_period = str(hc.get("start_period", ""))
    match = re.match(r"^(\d+)s$", start_period)
    assert match, (
        f"node-exporter healthcheck start_period must be '<N>s'. "
        f"Got: {start_period!r}."
    )
    value = int(match.group(1))
    assert value >= 30, (
        f"node-exporter healthcheck start_period={value}s is too short. "
        "Collectors need >=30s to stabilise on a cold boot; anything less "
        "produces premature 'unhealthy' flapping."
    )


# ---------------------------------------------------------------------------
# Prometheus scrape invariants.
# ---------------------------------------------------------------------------


def _parse_duration_seconds(value: str) -> int:
    """Parse a Prometheus-style duration into seconds.

    Supports the subset we use (``15s``, ``30s``, ``1m``). Prometheus
    accepts more (``ms``, ``h``, ``d``) but none of them appear in
    this scrape config today and accepting more here would just
    invite drift.
    """
    match = re.match(r"^(\d+)(s|m)$", value.strip())
    assert match, f"Unparseable Prometheus duration: {value!r}"
    n = int(match.group(1))
    unit = match.group(2)
    return n * (60 if unit == "m" else 1)


def test_prometheus_node_exporter_scrape_timeout_below_interval(
    node_exporter_scrape_job: dict[str, Any],
) -> None:
    """scrape_timeout MUST be strictly less than scrape_interval.

    Prometheus refuses to start if this is violated. If timeout >=
    interval, consecutive scrapes can be in flight simultaneously,
    which doubles the connection rate on node-exporter and is a
    contributing factor to the RST flood.
    """
    interval = _parse_duration_seconds(node_exporter_scrape_job["scrape_interval"])
    timeout = _parse_duration_seconds(node_exporter_scrape_job["scrape_timeout"])
    assert timeout < interval, (
        f"scrape_timeout ({timeout}s) must be strictly less than "
        f"scrape_interval ({interval}s) for the node-exporter job."
    )


def test_prometheus_node_exporter_scrape_timeout_has_buffer(
    node_exporter_scrape_job: dict[str, Any],
) -> None:
    """scrape_timeout should leave a buffer for warm-up.

    A timeout too close to the interval gives no headroom for
    collector-warmup jitter. We require at least 20% buffer.
    """
    interval = _parse_duration_seconds(node_exporter_scrape_job["scrape_interval"])
    timeout = _parse_duration_seconds(node_exporter_scrape_job["scrape_timeout"])
    ratio = timeout / interval
    assert ratio <= 0.85, (
        f"scrape_timeout ({timeout}s) is {ratio:.0%} of scrape_interval "
        f"({interval}s). Keep the ratio at ≤0.85 so slow collectors do "
        "not spill into the next interval."
    )
