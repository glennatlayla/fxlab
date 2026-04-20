"""
Unit tests for observability correctness (Tranche B — 2026-04-20 audit).

Context
-------
The 2026-04-20 production-readiness audit found two classes of
observability bugs in the prod stack:

1. **Alert rules referencing metrics that do not exist on this
   deployment.** ``alerts.yml`` inherited rules written for a
   Kubernetes target (``kube_pod_container_status_restarts_total``)
   and for postgres/redis exporters that were never added to the
   compose file (``pg_disk_usage_bytes``, ``pg_disk_capacity_bytes``).
   These alerts will never fire, giving operators a false sense of
   coverage.

2. **No exporters for postgres or redis.** The redis and postgres
   memory/disk alerts use valid exporter metric names, but the
   matching ``postgres-exporter`` / ``redis-exporter`` services
   were absent from the compose file and Prometheus scrape config.

Tranche B remediation:
  - Remove / replace alert rules that reference non-existent metrics.
  - Add ``postgres-exporter`` and ``redis-exporter`` sidecars.
  - Update ``prometheus.yml`` with matching scrape jobs.

This module locks the invariants so regressions are caught at pytest
time, not after a trading-safety alert silently fails to page.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths (resolved once at import time so missing files fail loudly early)
# ---------------------------------------------------------------------------

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_COMPOSE_PATH: Path = _PROJECT_ROOT / "docker-compose.prod.yml"
_PROM_CONFIG_PATH: Path = _PROJECT_ROOT / "deploy" / "prometheus" / "prometheus.yml"
_ALERTS_PATH: Path = _PROJECT_ROOT / "deploy" / "prometheus" / "alerts.yml"


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

#: Metrics that are known to NOT exist on a docker-compose deployment.
#: An alert referencing any of these can never fire. The hygiene test
#: rejects any occurrence of these names in the alerts file.
FORBIDDEN_METRIC_NAMES: frozenset[str] = frozenset(
    {
        # Kubernetes kube-state-metrics — unavailable on compose
        "kube_pod_container_status_restarts_total",
        "kube_pod_status_phase",
        "kube_deployment_status_replicas",
        # Legacy names from an earlier postgres_exporter or hand-rolled
        # exporter. postgres_exporter exposes pg_database_size_bytes
        # instead. See Tranche B remediation.
        "pg_disk_usage_bytes",
        "pg_disk_capacity_bytes",
    }
)

#: Exporter sidecars that MUST exist in the compose file so their
#: metrics are actually collected by Prometheus.
REQUIRED_EXPORTER_SERVICES: dict[str, dict[str, Any]] = {
    "postgres-exporter": {
        "image_prefix": "quay.io/prometheuscommunity/postgres-exporter",
        "scrape_port": 9187,
        "depends_on_service": "postgres",
    },
    "redis-exporter": {
        "image_prefix": "oliver006/redis_exporter",
        "scrape_port": 9121,
        "depends_on_service": "redis",
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_config() -> dict[str, Any]:
    assert _COMPOSE_PATH.is_file(), f"compose file not found: {_COMPOSE_PATH}"
    with _COMPOSE_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@pytest.fixture(scope="module")
def compose_services(compose_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return compose_config.get("services", {}) or {}


@pytest.fixture(scope="module")
def prometheus_config() -> dict[str, Any]:
    assert _PROM_CONFIG_PATH.is_file(), f"prometheus config not found: {_PROM_CONFIG_PATH}"
    with _PROM_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@pytest.fixture(scope="module")
def alerts_text() -> str:
    assert _ALERTS_PATH.is_file(), f"alerts file not found: {_ALERTS_PATH}"
    return _ALERTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def alerts_config(alerts_text: str) -> dict[str, Any]:
    return yaml.safe_load(alerts_text) or {}


# ---------------------------------------------------------------------------
# Alert-rule correctness
# ---------------------------------------------------------------------------


def _iter_alert_expressions(alerts_doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Yield (alert_name, expr) pairs across all groups.

    ``alerts.yml`` uses the prometheus ``groups: [{name, rules: [...]}]``
    shape. Each rule has either ``alert:`` or ``record:`` + ``expr:``.
    """
    results: list[tuple[str, str]] = []
    for group in alerts_doc.get("groups", []) or []:
        for rule in group.get("rules", []) or []:
            expr = rule.get("expr")
            name = rule.get("alert") or rule.get("record") or "<unnamed>"
            if expr is not None:
                results.append((str(name), str(expr)))
    return results


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_METRIC_NAMES))
def test_alerts_do_not_reference_forbidden_metric(
    alerts_text: str,
    forbidden: str,
) -> None:
    """No alert may reference a metric that doesn't exist on this deployment.

    References to Kubernetes-only or missing-exporter metrics produce
    alerts that cannot fire — the operator believes coverage exists
    when it does not.
    """
    # Use word-boundary regex so 'pg_disk_usage_bytes' doesn't
    # match 'pg_disk_usage_bytes_ratio' if someone adds that later.
    pattern = re.compile(rf"\b{re.escape(forbidden)}\b")
    hits = [
        i
        for i, line in enumerate(alerts_text.splitlines(), 1)
        if pattern.search(line) and not line.lstrip().startswith("#")
    ]
    assert not hits, (
        f"alerts.yml contains {len(hits)} reference(s) to forbidden "
        f"metric {forbidden!r} on lines {hits}. This metric does not "
        "exist on the docker-compose deployment and any alert "
        "referencing it will never fire. See Tranche B remediation."
    )


def test_every_alert_has_a_non_empty_expr(
    alerts_config: dict[str, Any],
) -> None:
    """Every rule has a non-empty ``expr:`` string.

    Defends against a copy/paste regression where a rule is added
    without its expression — prometheus silently skips such rules.
    """
    bad: list[str] = []
    for name, expr in _iter_alert_expressions(alerts_config):
        if not expr.strip():
            bad.append(name)
    assert not bad, f"Alerts with empty expr: {bad!r}"


# ---------------------------------------------------------------------------
# Exporter service presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("svc_name", sorted(REQUIRED_EXPORTER_SERVICES.keys()))
def test_exporter_service_exists_with_pinned_image(
    compose_services: dict[str, dict[str, Any]],
    svc_name: str,
) -> None:
    """Each exporter must be declared with a pinned (non-floating) image."""
    assert svc_name in compose_services, (
        f"Expected exporter service {svc_name!r} is missing from compose. "
        "Prometheus scrape targets for this exporter will always be down."
    )
    svc = compose_services[svc_name]
    image = str(svc.get("image") or "")
    spec = REQUIRED_EXPORTER_SERVICES[svc_name]
    expected_prefix = spec["image_prefix"]
    assert image.startswith(expected_prefix), (
        f"{svc_name} image {image!r} must start with {expected_prefix!r}."
    )
    assert ":" in image, f"{svc_name} image must be pinned to a specific tag. Got: {image!r}"
    tag = image.rsplit(":", 1)[1]
    assert tag not in {"latest", "edge", "stable"}, (
        f"{svc_name} image uses floating tag {tag!r}. Pin to an explicit version."
    )


@pytest.mark.parametrize("svc_name", sorted(REQUIRED_EXPORTER_SERVICES.keys()))
def test_exporter_service_depends_on_its_target_healthy(
    compose_services: dict[str, dict[str, Any]],
    svc_name: str,
) -> None:
    """Exporters must depend on their target with ``service_healthy``.

    Otherwise the exporter starts, finds the target unreachable,
    and Prometheus scrape failures pollute the health dashboard
    with noise that operators learn to ignore.
    """
    spec = REQUIRED_EXPORTER_SERVICES[svc_name]
    target = spec["depends_on_service"]
    svc = compose_services.get(svc_name, {})
    depends_on = svc.get("depends_on") or {}
    assert target in depends_on, f"{svc_name} must depend on {target!r} — got {depends_on!r}"
    entry = depends_on[target]
    if isinstance(entry, dict):
        assert entry.get("condition") == "service_healthy", (
            f"{svc_name} must depend on {target} with condition: service_healthy. "
            f"Got condition={entry.get('condition')!r}."
        )
    else:
        pytest.fail(
            f"{svc_name}.depends_on.{target} must be the long-form dict with "
            f"condition: service_healthy; short-form {entry!r} is not enough."
        )


@pytest.mark.parametrize("svc_name", sorted(REQUIRED_EXPORTER_SERVICES.keys()))
def test_exporter_service_exposes_scrape_port(
    compose_services: dict[str, dict[str, Any]],
    svc_name: str,
) -> None:
    """Each exporter exposes its scrape port on the compose network only.

    ``expose:`` (not ``ports:``) is correct — the scrape target is
    internal to the compose network; there's no reason to publish
    exporter metrics to the host.
    """
    spec = REQUIRED_EXPORTER_SERVICES[svc_name]
    expected_port = spec["scrape_port"]
    svc = compose_services.get(svc_name, {})
    exposed = [str(p) for p in (svc.get("expose") or [])]
    assert str(expected_port) in exposed, (
        f"{svc_name} must expose port {expected_port}; got {exposed!r}."
    )


# ---------------------------------------------------------------------------
# Prometheus scrape config
# ---------------------------------------------------------------------------


def _scrape_jobs(prom_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return {job_name: job_config} for all scrape_configs."""
    jobs: dict[str, dict[str, Any]] = {}
    for job in prom_cfg.get("scrape_configs", []) or []:
        name = job.get("job_name")
        if name:
            jobs[str(name)] = job
    return jobs


@pytest.mark.parametrize("svc_name", sorted(REQUIRED_EXPORTER_SERVICES.keys()))
def test_prometheus_has_scrape_job_for_exporter(
    prometheus_config: dict[str, Any],
    svc_name: str,
) -> None:
    """Prometheus must be configured to scrape each exporter.

    The scrape job's ``static_configs.targets`` entry must reference
    the exporter's compose service name + scrape port.
    """
    spec = REQUIRED_EXPORTER_SERVICES[svc_name]
    port = spec["scrape_port"]
    jobs = _scrape_jobs(prometheus_config)
    # Job name convention is the service name verbatim, but we accept
    # any job whose static_configs reference the correct target.
    expected_target = f"{svc_name}:{port}"
    found_in_job = None
    for job_name, job in jobs.items():
        for sc in job.get("static_configs", []) or []:
            for target in sc.get("targets", []) or []:
                if str(target) == expected_target:
                    found_in_job = job_name
                    break
            if found_in_job:
                break
        if found_in_job:
            break
    assert found_in_job, (
        f"prometheus.yml must have a scrape_config targeting {expected_target!r}. "
        f"Current jobs: {sorted(jobs.keys())!r}."
    )


def test_prometheus_scrape_intervals_are_reasonable(
    prometheus_config: dict[str, Any],
) -> None:
    """Every scrape job's interval is between 10s and 60s.

    Faster than 10s pegs prometheus CPU; slower than 60s produces
    alert-relevant data that is too stale. Both cases degrade
    observability quality.
    """
    pattern = re.compile(r"^(\d+)([smh])$")
    offenders: dict[str, str] = {}
    for name, job in _scrape_jobs(prometheus_config).items():
        interval = job.get("scrape_interval") or prometheus_config.get("global", {}).get(
            "scrape_interval"
        )
        if interval is None:
            continue
        m = pattern.match(str(interval))
        if not m:
            offenders[name] = f"unparseable scrape_interval={interval!r}"
            continue
        n = int(m.group(1))
        unit = m.group(2)
        seconds = n if unit == "s" else (n * 60 if unit == "m" else n * 3600)
        if seconds < 10 or seconds > 60:
            offenders[name] = f"scrape_interval={interval!r} (out of 10s..60s range)"
    assert not offenders, f"Out-of-range scrape intervals: {offenders!r}"


# ---------------------------------------------------------------------------
# ContainerRestarting alert must use a metric that exists on cadvisor
# ---------------------------------------------------------------------------


def test_container_restarting_alert_uses_cadvisor_metric(
    alerts_config: dict[str, Any],
) -> None:
    """The ContainerRestarting alert must use ``container_start_time_seconds``.

    cadvisor does not export a direct "restart count" metric; the
    idiomatic replacement on docker-compose is
    ``changes(container_start_time_seconds[window]) > N`` which
    counts distinct container start epochs in the window.
    """
    for name, expr in _iter_alert_expressions(alerts_config):
        if name == "ContainerRestarting":
            assert "container_start_time_seconds" in expr, (
                f"ContainerRestarting alert must use "
                "container_start_time_seconds (cadvisor-native). "
                f"Got expr: {expr!r}."
            )
            return
    # If the alert has been renamed or removed entirely, that's also
    # acceptable (Tranche B may have removed it). We only enforce the
    # shape if the alert is present.
