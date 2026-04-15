"""
Unit tests for docker-compose cascade safety (Commit B3 — 2026-04-15 remediation).

Context
-------
During the 2026-04-15 minitux install failure, a client-side Redis TCP keepalive
defect caused the ``api`` container to exit repeatedly. Because every dependent
service (at the time ``web``) was wired with
``depends_on: condition: service_healthy``, the cascade left the frontend
container parked in ``created`` state forever, while the installer printed the
interleaved logs of *all* containers. The root-cause service (api) was buried.

This suite locks in the cascade-safety invariants that Commit B3 establishes:

1. **Genuine startup-ordering edges use ``service_healthy``.** An edge is
   "genuine" when the dependent service cannot perform its startup sequence
   until the upstream service is reachable AND returning success (e.g. api
   performs a synchronous Redis ``PING`` during lifespan startup; keycloak
   writes its schema to postgres during boot).

2. **Non-genuine edges use ``service_started``.** These exist only so docker
   compose orders the ``docker compose up`` log output sensibly; the dependent
   service can tolerate the upstream being temporarily unavailable (web is
   served as a static SPA and renders "backend unavailable" gracefully; api
   fetches Keycloak JWKS lazily on first authenticated request, not at
   startup).

3. **Every service at the tail of a ``service_healthy`` edge must itself
   expose a healthcheck.** Otherwise the dependent will wait forever for a
   state the upstream cannot reach.

4. **No cycles** — ``depends_on`` is a DAG. Cycles cause compose to refuse
   to start the stack.

These invariants are asserted by parsing ``docker-compose.yml`` directly.
The file is authoritative. If the file drifts from these rules, this test
fails BEFORE the change hits minitux, which is exactly the regression
signal B3 is designed to produce.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Expected cascade-safety contract (source of truth for this test module).
# ---------------------------------------------------------------------------
#
# The format is:
#   (upstream_service, downstream_service, expected_condition)
#
# ``expected_condition`` is either ``"service_healthy"`` (genuine ordering,
# must wait for upstream to report healthy) or ``"service_started"``
# (non-genuine — container order only; downstream tolerates upstream
# unavailability).
#
# Adding / removing edges here is the gate for changing the compose graph.
# If the compose file changes and this list does not, the test fails and
# forces the reviewer to justify the change by updating both.
# ---------------------------------------------------------------------------

GENUINE_HEALTHY_EDGES: list[tuple[str, str]] = [
    # api performs a blocking Redis PING inside the lifespan startup phase.
    # If redis is not healthy, api cannot complete startup. Genuine.
    ("redis", "api"),
    # api runs migrations and validates required secrets against postgres
    # during the lifespan startup phase. If postgres is not healthy, api
    # cannot complete startup. Genuine.
    ("postgres", "api"),
    # keycloak persists its realm/user schema in postgres during boot.
    # If postgres is not healthy, keycloak will crashloop. Genuine.
    ("postgres", "keycloak"),
]

CASCADE_SAFE_STARTED_EDGES: list[tuple[str, str]] = [
    # api fetches Keycloak JWKS lazily on the first authenticated request
    # (see KeycloakTokenValidator — it is not invoked during lifespan
    # startup). api can therefore start and serve ``/health`` without
    # keycloak being healthy. If keycloak is truly down, auth requests
    # return 503, which is the correct observable behaviour rather than
    # a hung container stack.
    ("keycloak", "api"),
    # web is an nginx-served static SPA. It does not require api to be
    # healthy — on the contrary, users benefit from seeing the SPA render
    # "backend unavailable" messaging rather than staring at a blank
    # ``created``-state container. service_started preserves log ordering
    # without creating a cascade failure.
    ("api", "web"),
]

# Fixed set of services we expect in the compose file at this milestone.
# If a new service is added, this list must be updated alongside the
# appropriate depends_on edges so cascade safety is re-evaluated.
EXPECTED_SERVICES: frozenset[str] = frozenset(
    {"api", "web", "keycloak", "postgres", "redis", "jaeger"}
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_path() -> Path:
    """Locate ``docker-compose.yml`` at the repository root."""
    # tests/unit/<this file> → project root is two levels up.
    root = Path(__file__).resolve().parents[2]
    path = root / "docker-compose.yml"
    if not path.is_file():
        pytest.fail(f"docker-compose.yml not found at {path}")
    return path


@pytest.fixture(scope="module")
def compose_config(compose_path: Path) -> dict[str, Any]:
    """Parse ``docker-compose.yml`` once per module."""
    with compose_path.open("r", encoding="utf-8") as handle:
        parsed = yaml.safe_load(handle)
    assert isinstance(parsed, dict), "docker-compose.yml root must be a mapping"
    assert "services" in parsed, "docker-compose.yml must declare a 'services' block"
    return parsed


def _depends_on(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Return a normalised ``depends_on`` mapping for a service.

    The compose spec allows both a list form (``depends_on: [a, b]``) and a
    mapping form (``depends_on: {a: {condition: service_healthy}}``). This
    helper normalises to the mapping form so callers can always look up
    ``.get("condition")``. A service without ``depends_on`` yields an empty
    mapping.
    """
    raw = service.get("depends_on")
    if raw is None:
        return {}
    if isinstance(raw, list):
        # List form has no conditions → treat as "service_started" semantics,
        # which is compose's implicit default for the list form.
        return {name: {"condition": "service_started"} for name in raw}
    if isinstance(raw, dict):
        normalised: dict[str, dict[str, Any]] = {}
        for name, spec in raw.items():
            if isinstance(spec, dict):
                normalised[name] = spec
            else:
                normalised[name] = {"condition": "service_started"}
        return normalised
    pytest.fail(f"Unrecognised depends_on form: {type(raw).__name__}")


# ---------------------------------------------------------------------------
# Tests — service set
# ---------------------------------------------------------------------------


def test_expected_services_are_present(compose_config: dict[str, Any]) -> None:
    """Compose file must declare exactly the services B3 reasoned about.

    If a service is added or removed, cascade safety must be re-evaluated —
    this test forces the author to update EXPECTED_SERVICES (and therefore
    to confirm they inspected each new edge).
    """
    actual = set(compose_config["services"].keys())
    assert actual == EXPECTED_SERVICES, (
        "docker-compose.yml service set drifted from B3 cascade-safety contract. "
        f"Expected {sorted(EXPECTED_SERVICES)}, got {sorted(actual)}. "
        "Update EXPECTED_SERVICES and GENUINE_HEALTHY_EDGES / "
        "CASCADE_SAFE_STARTED_EDGES in this test module after reviewing the "
        "cascade semantics of the new / removed service."
    )


# ---------------------------------------------------------------------------
# Tests — genuine service_healthy edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("upstream", "downstream"), GENUINE_HEALTHY_EDGES)
def test_genuine_healthy_edges_use_service_healthy(
    compose_config: dict[str, Any],
    upstream: str,
    downstream: str,
) -> None:
    """Every edge in GENUINE_HEALTHY_EDGES must use ``service_healthy``.

    These edges represent ordering the downstream genuinely requires — e.g.
    api cannot complete its lifespan startup without Redis returning PONG.
    Relaxing these would let a half-booted api accept traffic before its
    prerequisites were ready, which is worse than a startup failure.
    """
    downstream_service = compose_config["services"][downstream]
    deps = _depends_on(downstream_service)
    assert upstream in deps, (
        f"'{downstream}' must declare depends_on for '{upstream}' "
        f"(it is a genuine startup-ordering prerequisite)."
    )
    condition = deps[upstream].get("condition")
    assert condition == "service_healthy", (
        f"'{downstream}' → '{upstream}' edge MUST use condition: service_healthy "
        f"(genuine startup ordering prerequisite). Got: {condition!r}."
    )


# ---------------------------------------------------------------------------
# Tests — cascade-safe service_started edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("upstream", "downstream"), CASCADE_SAFE_STARTED_EDGES)
def test_cascade_safe_edges_do_not_use_service_healthy(
    compose_config: dict[str, Any],
    upstream: str,
    downstream: str,
) -> None:
    """Cascade-safe edges must NOT use ``service_healthy``.

    These edges exist for log ordering only; the downstream tolerates the
    upstream being temporarily unavailable. If one of these is accidentally
    upgraded to service_healthy, a single-service failure (e.g. api exits
    with code 3 after Redis keepalive EINVAL) will hang the dependent
    container in 'created' state forever — exactly the 2026-04-15 minitux
    cascade B3 was created to prevent.
    """
    downstream_service = compose_config["services"][downstream]
    deps = _depends_on(downstream_service)
    assert upstream in deps, (
        f"'{downstream}' must still declare depends_on for '{upstream}' "
        f"(kept for docker compose log ordering), but with "
        f"condition: service_started, not service_healthy."
    )
    condition = deps[upstream].get("condition")
    assert condition != "service_healthy", (
        f"'{downstream}' → '{upstream}' edge MUST NOT use service_healthy. "
        f"Reason: the 2026-04-15 minitux cascade (B3 remediation). "
        f"Use condition: service_started so a failing '{upstream}' does not "
        f"park '{downstream}' in created-state indefinitely."
    )
    # service_started is the prescribed condition for cascade-safe ordering.
    # A missing condition falls back to service_started in compose, which is
    # acceptable but less explicit — we require the explicit form.
    assert condition == "service_started", (
        f"'{downstream}' → '{upstream}' edge must declare "
        f"condition: service_started explicitly (got {condition!r}). "
        f"Explicit conditions are mandatory so reviewers see the cascade "
        f"policy at the edge site without having to remember compose "
        f"defaults."
    )


# ---------------------------------------------------------------------------
# Tests — global invariants across all edges
# ---------------------------------------------------------------------------


def test_every_depends_on_edge_is_classified(compose_config: dict[str, Any]) -> None:
    """Every edge in the compose file must appear in one of the two lists.

    This prevents "silent" edges — a reviewer adding a depends_on without
    updating this module would bypass the cascade-safety review. The test
    fails loudly, forcing classification.
    """
    classified: set[tuple[str, str]] = set(GENUINE_HEALTHY_EDGES) | set(
        CASCADE_SAFE_STARTED_EDGES
    )
    discovered: set[tuple[str, str]] = set()
    for downstream_name, service in compose_config["services"].items():
        for upstream_name in _depends_on(service):
            discovered.add((upstream_name, downstream_name))

    unclassified = discovered - classified
    stale = classified - discovered

    assert not unclassified, (
        "docker-compose.yml introduced depends_on edges not classified in "
        "this test's cascade-safety contract. Add each new edge to either "
        "GENUINE_HEALTHY_EDGES or CASCADE_SAFE_STARTED_EDGES with a "
        "rationale comment. New edges: "
        f"{sorted(unclassified)}."
    )
    assert not stale, (
        "Cascade-safety contract references edges no longer present in "
        "docker-compose.yml. Remove them from the classification lists. "
        f"Stale: {sorted(stale)}."
    )


def test_service_healthy_upstreams_have_healthchecks(
    compose_config: dict[str, Any],
) -> None:
    """Any service at the tail of a service_healthy edge must define a healthcheck.

    Otherwise the dependent waits forever for a state the upstream cannot
    reach. This is a correctness guard — compose does not enforce it
    automatically.
    """
    services = compose_config["services"]
    for downstream_name, service in services.items():
        for upstream_name, spec in _depends_on(service).items():
            if spec.get("condition") != "service_healthy":
                continue
            upstream_service = services.get(upstream_name)
            assert upstream_service is not None, (
                f"'{downstream_name}' declares service_healthy dependency on "
                f"'{upstream_name}', but that service is not defined."
            )
            assert "healthcheck" in upstream_service, (
                f"'{downstream_name}' depends on '{upstream_name}' with "
                f"condition: service_healthy, but '{upstream_name}' has no "
                f"healthcheck. The dependent would wait forever."
            )


def test_depends_on_graph_is_acyclic(compose_config: dict[str, Any]) -> None:
    """depends_on must form a DAG — compose refuses to start a cyclic stack.

    Uses iterative DFS with a colour map (WHITE / GRAY / BLACK). If we
    encounter a GRAY node while exploring, a cycle exists.
    """
    services = compose_config["services"]

    # Build adjacency: downstream → list of upstreams it waits on.
    adjacency: dict[str, list[str]] = defaultdict(list)
    for downstream_name, service in services.items():
        for upstream_name in _depends_on(service):
            adjacency[downstream_name].append(upstream_name)

    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = dict.fromkeys(services, WHITE)

    def visit(start: str) -> None:
        # Explicit stack so recursion depth is not bounded by Python limits.
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, child_idx = stack[-1]
            if colour[node] == WHITE:
                colour[node] = GRAY
            neighbours = adjacency.get(node, [])
            if child_idx >= len(neighbours):
                colour[node] = BLACK
                stack.pop()
                continue
            child = neighbours[child_idx]
            stack[-1] = (node, child_idx + 1)
            child_colour = colour.get(child, WHITE)
            if child_colour == GRAY:
                cycle_path = [n for n, _ in stack] + [child]
                pytest.fail(
                    "depends_on cycle detected: " + " → ".join(cycle_path)
                )
            if child_colour == WHITE:
                stack.append((child, 0))

    for name in services:
        if colour[name] == WHITE:
            visit(name)


def test_web_start_does_not_require_api_healthy(
    compose_config: dict[str, Any],
) -> None:
    """Regression guard for the exact 2026-04-15 minitux cascade.

    On 2026-04-15, a Redis client-side EINVAL caused api to exit
    repeatedly. ``web`` had ``depends_on: api: condition: service_healthy``,
    so the installer's ``docker compose up`` blocked indefinitely with
    ``web`` parked in ``created`` state. The operator saw "web failed to
    start" rather than "api is crashlooping on Redis".

    This test asserts the exact edge is NOT service_healthy. A future
    refactor that re-introduces the cascade will trip this guard by name.
    """
    web_deps = _depends_on(compose_config["services"]["web"])
    api_condition = web_deps.get("api", {}).get("condition")
    assert api_condition != "service_healthy", (
        "Cascade regression: web→api is back on service_healthy. "
        "This reverts the B3 remediation — see "
        "docs/remediation/2026-04-15-minitux-install-failure.md (Commit 6)."
    )
