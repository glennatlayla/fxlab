"""
Unit tests for compose security hardening (Tranche C — 2026-04-20 audit).

Context
-------
The 2026-04-20 production-readiness audit called out three security
gaps in ``docker-compose.prod.yml``:

1. No service declares ``security_opt: [no-new-privileges:true]``,
   so any setuid binary inside a container could escalate privileges
   above what the image's USER directive specifies.

2. Only cadvisor legitimately needs ``privileged: true`` (to access
   cgroup filesystem on cgroupsv2 hosts). There's no regression
   guard preventing a future edit from silently adding ``privileged:
   true`` to another service.

3. ``node-exporter`` reads host metrics via read-only bind mounts
   and never writes to its own rootfs, yet runs with a writable
   rootfs — unnecessary attack surface.

Tranche C remediation scope intentionally excludes cap_drop/cap_add
tuning. Getting capabilities wrong on postgres (initdb needs CHOWN,
FOWNER), nginx (NET_BIND_SERVICE for port 80/443), or cadvisor
(privileged supersedes caps) silently breaks those services in
production — and this sandbox cannot run docker to validate.
Cap tuning is deferred to a future tranche that can be validated
with real-container smoke on minitux.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

#: The single service permitted to run with ``privileged: true``.
#: cadvisor requires this on cgroupsv2 hosts (kernel 6.x / Ubuntu
#: 22.04+ / RHEL 9+) to access cgroup filesystem and /dev/kmsg.
#: The existing cadvisor service comment documents the rationale.
PRIVILEGED_ALLOWLIST: frozenset[str] = frozenset({"cadvisor"})

#: Services whose rootfs MUST be read-only. These services do not
#: need to write to their own filesystem — everything they produce
#: is written via bind mounts / named volumes. Making rootfs read-
#: only prevents an attacker who achieves RCE from modifying the
#: binary / libraries / config in place.
REQUIRED_READONLY_ROOTFS_SERVICES: frozenset[str] = frozenset(
    {
        # node-exporter reads /proc, /sys, / via read-only bind
        # mounts; its own writes (if any) go to /tmp via --collector
        # flags. The rootfs is safely read-only.
        "node-exporter",
    }
)

#: The security_opt entry every non-cadvisor service must declare.
#: cadvisor is excluded because privileged:true already implies
#: every capability — no-new-privileges is redundant there and, on
#: some kernels, interacts poorly with cgroup v2 device access.
REQUIRED_SECURITY_OPT_NNP: str = "no-new-privileges:true"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    path = root / "docker-compose.prod.yml"
    assert path.is_file(), f"compose file not found at {path}"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@pytest.fixture(scope="module")
def compose_services(compose_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services = compose_config.get("services") or {}
    assert services, "compose file must define services"
    return services


# ---------------------------------------------------------------------------
# privileged: regression guard
# ---------------------------------------------------------------------------


def test_only_allowlisted_services_run_privileged(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """No service outside the allowlist may set ``privileged: true``.

    privileged=true grants full host access — device control, kernel
    module load, arbitrary mount. It's required for cadvisor on
    cgroupsv2 but an outright security hole anywhere else.
    """
    offenders: list[str] = []
    for name, svc in compose_services.items():
        if bool(svc.get("privileged")) and name not in PRIVILEGED_ALLOWLIST:
            offenders.append(name)
    assert not offenders, (
        f"Services with privileged: true outside the allowlist "
        f"{sorted(PRIVILEGED_ALLOWLIST)}: {offenders!r}. "
        "privileged:true grants host-level access. If a new service "
        "genuinely needs it, add it to PRIVILEGED_ALLOWLIST here and "
        "document the kernel-level reason in the compose comment."
    )


def test_allowlisted_privileged_services_actually_declare_privileged(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """If a service is on the privileged allowlist, it must actually need it.

    Guards against stale allowlist: if cadvisor stops needing privileged
    (e.g. docker gains unprivileged cadvisor support), we want a
    failing test to flag the allowlist as no longer justified.
    """
    for name in PRIVILEGED_ALLOWLIST:
        if name not in compose_services:
            pytest.skip(f"allowlisted service {name!r} not present in compose")
        svc = compose_services[name]
        assert bool(svc.get("privileged")), (
            f"{name} is on the privileged allowlist but does NOT actually "
            "set privileged:true. Either remove it from the allowlist "
            "(good — security win) or restore privileged:true."
        )


# ---------------------------------------------------------------------------
# no-new-privileges
# ---------------------------------------------------------------------------


def test_every_service_sets_no_new_privileges(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Every service must declare no-new-privileges:true.

    Even if a container's USER is fxlab, a setuid binary inside the
    container image (unintentional or supply-chain-planted) could
    escalate to root. no-new-privileges:true blocks that escalation
    at the kernel level.

    Applied to every service including cadvisor: for a privileged
    container the flag is effectively a no-op (privileged already
    implies all caps) but uniformity simplifies the contract and
    guards against someone later removing privileged without
    adding the flag.
    """
    offenders: list[str] = []
    for name, svc in compose_services.items():
        sec_opts = svc.get("security_opt") or []
        sec_opts_str = {str(x) for x in sec_opts}
        if REQUIRED_SECURITY_OPT_NNP not in sec_opts_str:
            offenders.append(name)
    assert not offenders, (
        f"Services missing security_opt: [{REQUIRED_SECURITY_OPT_NNP}]: "
        f"{offenders!r}. This flag blocks privilege escalation via "
        "setuid binaries — a cheap, blanket security win that only "
        "breaks services that legitimately depend on setuid inside "
        "the container (none of ours do)."
    )


def test_security_opt_uses_list_form(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """``security_opt`` must be a YAML list, not a string.

    Compose accepts both, but the string form admits shell-quoting
    bugs (same class as the cadvisor command-list issue). Force list
    form at contract time.
    """
    bad: dict[str, str] = {}
    for name, svc in compose_services.items():
        sec = svc.get("security_opt")
        if sec is None:
            continue
        if not isinstance(sec, list):
            bad[name] = type(sec).__name__
    assert not bad, (
        f"Services with non-list security_opt: {bad!r}. "
        'Use YAML list form: security_opt: ["no-new-privileges:true"].'
    )


# ---------------------------------------------------------------------------
# read_only rootfs
# ---------------------------------------------------------------------------


def test_services_requiring_readonly_rootfs_have_it(
    compose_services: dict[str, dict[str, Any]],
) -> None:
    """Services on the read-only allowlist must set ``read_only: true``.

    These services don't need to write to their container rootfs; a
    read-only rootfs is a cheap hardening win that prevents an
    attacker who achieves RCE from modifying the binary/libs/config
    in place (they can still write to tmpfs-backed /tmp and to
    declared volumes, but not to /usr, /bin, /etc, etc.).
    """
    offenders: list[str] = []
    for name in REQUIRED_READONLY_ROOTFS_SERVICES:
        if name not in compose_services:
            pytest.fail(
                f"Expected service {name!r} missing from compose; "
                "update REQUIRED_READONLY_ROOTFS_SERVICES if intentionally removed."
            )
        if not bool(compose_services[name].get("read_only")):
            offenders.append(name)
    assert not offenders, (
        f"Services that should have read_only:true but don't: {offenders!r}. "
        "These services don't write to their rootfs; a read-only rootfs "
        "prevents in-place modification of binaries/libs/config after RCE."
    )
