"""
Unit tests for ``docker-compose.prod.yml`` robustness hygiene (Tranche A —
2026-04-20 production-hardening audit).

Context
-------
The 2026-04-15 minitux install failure (Redis TCP keepalive crashloop) and
the 2026-04-20 cAdvisor accelerator-flag failure both shared a pattern:
a service entered a broken state and the compose restart policy
(``unless-stopped``) looped it forever while nothing else in the stack
surfaced the failure. The installer's smoke test had gaps that allowed
either bug to ship.

The audit identified four classes of production-robustness gap that are
present across ALL nine services in ``docker-compose.prod.yml``:

1. **Unbounded restart policy.** Every service uses ``restart: unless-stopped``.
   The user's explicit directive (recorded in operator memory) is
   ``restart: on-failure:3`` — the installer must notify operators when a
   service exhausts its restart budget, rather than loop forever silently.

2. **No logging driver caps.** No service declares a ``logging:`` driver
   with size/file limits, so docker defaults to unbounded ``json-file``.
   A runaway service fills ``/var/lib/docker`` in hours → postgres writes
   fail → orders are lost. Same silent-failure class as the cadvisor bug.

3. **No resource reservations.** Every service has ``deploy.resources.limits``
   set but zero declare ``reservations``. Docker will overcommit — under
   memory pressure the kernel OOM-killer selects a victim based on
   heuristics that do not respect our safety-critical services (postgres,
   api). Reservations are the guarantee that postgres cannot be starved
   by a Prometheus query burst.

4. **Prometheus not reachable from the host.** Port 9090 is only ``expose``'d
   to the compose network, so ``curl localhost:9090`` from the host gets
   nothing. The remediation is a ``127.0.0.1:9090:9090`` binding — loopback
   only so the UI is reachable for operators without exposing it publicly.

Each test in this module locks one invariant. Adding or changing a service
in ``docker-compose.prod.yml`` that does not satisfy these invariants will
fail pytest BEFORE the change reaches minitux.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Contract constants — single source of truth for this module.
# ---------------------------------------------------------------------------

#: Every service defined in the prod compose file is expected to honour
#: the invariants below. We derive the list at fixture time rather than
#: hardcoding it here so the tests stay correct as services are added
#: or removed; hardcoding would create a silent drift risk identical to
#: the one §16 of CLAUDE.md was written to prevent.
#:
#: However, some invariants admit carve-outs for specific service
#: *kinds* (e.g. reservations are only required for the "critical"
#: services whose OOM kill is data-loss-grade). Those carve-outs are
#: enumerated as named sets below.

#: Services whose memory starvation causes data loss or customer-
#: visible outage. These MUST declare ``deploy.resources.reservations``
#: in addition to limits. Enforcing reservations on every service
#: would be over-strict (node-exporter, cadvisor, alertmanager are
#: cheap observers that can tolerate being squeezed under pressure).
CRITICAL_SERVICES_REQUIRING_RESERVATIONS: frozenset[str] = frozenset(
    {"api", "postgres", "redis", "nginx"}
)

#: Services that must be reachable from the host loopback interface
#: for operator workflows (Prometheus UI, Grafana if added later).
#: Mapping: service -> (host_ip, host_port, container_port).
SERVICES_REQUIRING_LOOPBACK_PORT: dict[str, tuple[str, int, int]] = {
    "prometheus": ("127.0.0.1", 9090, 9090),
}

#: Restart-policy short form the compose file must use. ``on-failure:3``
#: in compose (non-swarm) means "restart on non-zero exit, up to 3
#: attempts, then give up and let the operator see the exhausted state".
#: This is the shape recorded in the operator feedback memory.
EXPECTED_RESTART_POLICY: str = "on-failure:3"

#: Restart policy values that are explicitly forbidden — these are
#: the shapes the audit called out as unsafe (unbounded retry).
FORBIDDEN_RESTART_POLICIES: frozenset[str] = frozenset(
    {"always", "unless-stopped", "on-failure"}  # bare 'on-failure' = infinite retry
)

#: Accepted docker logging drivers. ``json-file`` is the default;
#: ``local`` is preferred for new deployments (better on-disk format);
#: ``journald`` and ``syslog`` are acceptable for hosts running a log
#: collector. We do NOT accept ``none`` because it drops logs entirely.
ACCEPTED_LOGGING_DRIVERS: frozenset[str] = frozenset({"json-file", "local", "journald", "syslog"})

#: Logging options that MUST be set to cap disk consumption. Keys are
#: driver-dependent: json-file/local accept ``max-size`` + ``max-file``.
REQUIRED_LOGGING_OPTIONS: tuple[str, ...] = ("max-size", "max-file")


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
    assert isinstance(parsed, dict), "compose root must be a mapping"
    return parsed


@pytest.fixture(scope="module")
def compose_services(compose_prod_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the ``services`` mapping."""
    services = compose_prod_config.get("services", {})
    assert isinstance(services, dict) and services, (
        "docker-compose.prod.yml must define at least one service"
    )
    return services


def _service_names(services: dict[str, dict[str, Any]]) -> list[str]:
    """Sorted list of service names for stable parametrisation."""
    return sorted(services.keys())


# ---------------------------------------------------------------------------
# Restart-policy invariants
# ---------------------------------------------------------------------------


def _all_service_params(services: dict[str, dict[str, Any]]) -> list[str]:
    """Helper — keeps parametrisation consistent across tests."""
    return _service_names(services)


def test_no_service_uses_forbidden_restart_policy(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """No service may use ``always``, ``unless-stopped``, or bare ``on-failure``.

    The 2026-04-20 cAdvisor incident was specifically worsened by
    ``unless-stopped``: the broken container looped forever on an
    invalid flag. ``on-failure:3`` would have made the container exit
    loudly after 3 tries so the installer / operator could see it.
    """
    offenders: dict[str, str] = {}
    for name, svc in compose_services.items():
        policy = svc.get("restart", "")
        if policy in FORBIDDEN_RESTART_POLICIES:
            offenders[name] = policy
    assert not offenders, (
        f"The following services use a forbidden restart policy "
        f"(no bounded retry): {offenders!r}. "
        f"All services must use restart: {EXPECTED_RESTART_POLICY!r} "
        "so a broken service exits cleanly after 3 attempts rather "
        "than loops forever silently. Operator memory records this "
        "as the required shape."
    )


def test_every_service_declares_bounded_restart_policy(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Every service declares ``restart: on-failure:<N>`` with N between 1 and 5.

    The specific form ``on-failure:3`` is the convention, but we accept
    any small N so an operator can legitimately tune a specific service
    (e.g. postgres might justify on-failure:5 for disk-blip resilience)
    without failing the hygiene contract. The forbidden set above
    already catches the unbounded shapes.
    """
    missing: list[str] = []
    bad_shape: dict[str, str] = {}
    pattern = re.compile(r"^on-failure:([1-5])$")
    for name, svc in compose_services.items():
        policy = svc.get("restart")
        if policy is None:
            missing.append(name)
            continue
        if not pattern.match(str(policy)):
            bad_shape[name] = str(policy)
    assert not missing, (
        f"Services without a restart policy: {missing!r}. "
        f"Every service MUST declare restart: {EXPECTED_RESTART_POLICY!r}."
    )
    assert not bad_shape, (
        f"Services with malformed restart policy: {bad_shape!r}. "
        f"Expected shape: on-failure:<N> where 1 <= N <= 5. "
        f"Recommended: {EXPECTED_RESTART_POLICY!r}."
    )


# ---------------------------------------------------------------------------
# Logging driver invariants
# ---------------------------------------------------------------------------


def test_every_service_declares_logging_driver(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Every service declares a ``logging:`` block with an accepted driver.

    Docker defaults to ``json-file`` with NO size cap when ``logging:``
    is absent. A chatty service can fill the host disk in hours.
    """
    missing: list[str] = []
    bad_driver: dict[str, str] = {}
    for name, svc in compose_services.items():
        logging = svc.get("logging")
        if not isinstance(logging, dict):
            missing.append(name)
            continue
        driver = logging.get("driver")
        if not driver:
            missing.append(name)
            continue
        if str(driver) not in ACCEPTED_LOGGING_DRIVERS:
            bad_driver[name] = str(driver)
    assert not missing, (
        f"Services missing logging:driver: {missing!r}. "
        "Without an explicit logging driver + size cap, docker's "
        "default json-file driver grows without bound and can fill "
        "the host disk, taking postgres writes offline."
    )
    assert not bad_driver, (
        f"Services with non-allowed logging driver: {bad_driver!r}. "
        f"Accepted drivers: {sorted(ACCEPTED_LOGGING_DRIVERS)!r}."
    )


def test_every_service_caps_log_size_and_file_count(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """``logging.options`` must set ``max-size`` AND ``max-file``.

    The json-file and local drivers both honour these options. A single
    cap without rotation (max-size only) still grows to ``max-size`` per
    file * unbounded files; both are required.
    """
    offenders: dict[str, list[str]] = {}
    for name, svc in compose_services.items():
        logging = svc.get("logging")
        if not isinstance(logging, dict):
            continue  # covered by previous test
        options = logging.get("options") or {}
        # Docker accepts option values as strings (YAML 1.1 gotcha — a
        # value like '10m' must be a string, not implicitly coerced).
        missing_opts = [opt for opt in REQUIRED_LOGGING_OPTIONS if opt not in options]
        if missing_opts:
            offenders[name] = missing_opts
    assert not offenders, (
        f"Services missing required logging options: {offenders!r}. "
        f"Every service MUST set BOTH {REQUIRED_LOGGING_OPTIONS!r} "
        "so container log files neither grow individually unbounded "
        "nor accumulate unboundedly."
    )


def test_log_size_cap_is_reasonable_value(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """``max-size`` must be parseable and at most 100m (docker suffix).

    100m per file * 5 files = 500m per container — a reasonable ceiling
    for a modestly-busy service before rotation kicks in. Larger values
    start to pressure the /var/lib/docker volume in aggregate.
    """
    offenders: dict[str, str] = {}
    pattern = re.compile(r"^(\d+)([kmg])$", re.IGNORECASE)
    for name, svc in compose_services.items():
        logging = svc.get("logging")
        if not isinstance(logging, dict):
            continue
        options = logging.get("options") or {}
        max_size = options.get("max-size")
        if max_size is None:
            continue  # covered by previous test
        m = pattern.match(str(max_size))
        if not m:
            offenders[name] = f"unparseable max-size={max_size!r}"
            continue
        size = int(m.group(1))
        unit = m.group(2).lower()
        # Convert to megabytes for comparison.
        mb = size if unit == "m" else (size * 1024 if unit == "g" else size / 1024)
        if mb > 100 or mb < 1:
            offenders[name] = f"max-size={max_size!r} is out of range (must be between 1m and 100m)"
    assert not offenders, f"Services with out-of-range max-size: {offenders!r}"


# ---------------------------------------------------------------------------
# Resource-reservation invariants
# ---------------------------------------------------------------------------


def test_critical_services_declare_memory_reservation(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Services whose OOM kill is data-loss-grade must declare reservations.

    Reservations are a minimum guarantee. Without them, docker may
    overcommit and the kernel picks a victim under pressure. Picking
    postgres as the OOM victim during a Prometheus query burst is
    exactly the class of silent failure this test prevents.
    """
    offenders: list[str] = []
    for svc_name in sorted(CRITICAL_SERVICES_REQUIRING_RESERVATIONS):
        if svc_name not in compose_services:
            pytest.fail(
                f"Expected critical service {svc_name!r} is missing from "
                "docker-compose.prod.yml. Update "
                "CRITICAL_SERVICES_REQUIRING_RESERVATIONS in this test "
                "module if the service was intentionally removed."
            )
        svc = compose_services[svc_name]
        deploy = svc.get("deploy") or {}
        resources = deploy.get("resources") or {}
        reservations = resources.get("reservations") or {}
        if not reservations.get("memory"):
            offenders.append(svc_name)
    assert not offenders, (
        f"Critical services missing deploy.resources.reservations.memory: "
        f"{offenders!r}. These services' OOM kill is data-loss grade; "
        "reservations are the only way to prevent overcommit from "
        "starving them under memory pressure."
    )


def test_reservations_do_not_exceed_limits(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Wherever both exist, ``reservations.memory <= limits.memory``.

    A reservation larger than the limit is a compose-time error that
    docker will reject — this test catches it before the operator
    tries to run ``docker compose up`` on minitux.
    """
    offenders: dict[str, dict[str, str]] = {}
    for name, svc in compose_services.items():
        deploy = svc.get("deploy") or {}
        resources = deploy.get("resources") or {}
        limits = resources.get("limits") or {}
        reservations = resources.get("reservations") or {}
        l_mem = _parse_memory(limits.get("memory"))
        r_mem = _parse_memory(reservations.get("memory"))
        if l_mem is not None and r_mem is not None and r_mem > l_mem:
            offenders[name] = {
                "limit": str(limits.get("memory")),
                "reservation": str(reservations.get("memory")),
            }
    assert not offenders, (
        f"Services where memory reservation exceeds limit: {offenders!r}. "
        "Docker will reject these at compose-time."
    )


def _parse_memory(value: Any) -> int | None:
    """Parse a docker-compose memory string (``256M``, ``1G``) into bytes.

    Returns None for missing / unparseable values so callers can skip
    comparison cleanly.
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    m = re.match(r"^(\d+)\s*([KMG]?)B?$", s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    factor = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[unit]
    return n * factor


# ---------------------------------------------------------------------------
# Port-exposure invariants
# ---------------------------------------------------------------------------


def test_prometheus_is_reachable_on_host_loopback(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Prometheus must have a ``127.0.0.1:9090:9090`` port binding.

    The 2026-04-20 audit revealed that ``curl localhost:9090`` from the
    host returned empty because prometheus only ``expose``'d 9090 to
    the compose network. Operators need host-local access to the
    Prometheus UI for diagnostics (e.g. the CPU-pegging investigation
    that prompted this hardening tranche).

    Loopback-only (127.0.0.1) binding is intentional: no public
    exposure of the Prometheus UI; only operators SSH'd into the host
    can reach it.
    """
    for svc_name, (host_ip, host_port, container_port) in SERVICES_REQUIRING_LOOPBACK_PORT.items():
        assert svc_name in compose_services, (
            f"Expected service {svc_name!r} missing from compose file"
        )
        svc = compose_services[svc_name]
        ports = svc.get("ports") or []
        assert isinstance(ports, list), (
            f"{svc_name}.ports must be a YAML list (string-form bindings admit shell-quoting bugs)"
        )
        expected_short = f"{host_ip}:{host_port}:{container_port}"
        matched = False
        for entry in ports:
            if isinstance(entry, str) and entry == expected_short:
                matched = True
                break
            if isinstance(entry, dict):
                if (
                    str(entry.get("host_ip")) == host_ip
                    and int(entry.get("published", 0)) == host_port
                    and int(entry.get("target", 0)) == container_port
                ):
                    matched = True
                    break
        assert matched, (
            f"{svc_name} must declare a loopback port binding "
            f"{expected_short!r}. Current ports={ports!r}."
        )


def test_no_service_exposes_a_port_on_all_interfaces(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """No ``ports:`` entry may bind to ``0.0.0.0`` or omit the host IP.

    Omitting the host IP (``"9090:9090"``) means docker binds to all
    interfaces — effectively publishing the port to the world. The
    only acceptable shapes are ``127.0.0.1:<host>:<container>`` or
    an explicit private address.

    ``expose:`` entries (compose-network-only) are unaffected by this
    test; only ``ports:`` entries are checked.
    """
    offenders: dict[str, list[str]] = {}
    public_bind_re = re.compile(r"^(?:0\.0\.0\.0:)?\d+:\d+$")
    for name, svc in compose_services.items():
        ports = svc.get("ports") or []
        svc_offenders: list[str] = []
        for entry in ports:
            entry_str = str(entry) if not isinstance(entry, dict) else ""
            if entry_str and public_bind_re.match(entry_str):
                svc_offenders.append(entry_str)
            elif isinstance(entry, dict):
                host_ip = entry.get("host_ip")
                if not host_ip or str(host_ip) in ("", "0.0.0.0"):
                    svc_offenders.append(str(entry))
        if svc_offenders:
            offenders[name] = svc_offenders
    assert not offenders, (
        f"Services binding ports to all interfaces: {offenders!r}. "
        "Use 127.0.0.1:<host>:<container> for host-local only exposure. "
        "Public exposure belongs in nginx + firewall, not compose."
    )
