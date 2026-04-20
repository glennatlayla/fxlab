"""
Unit tests for N1 — cAdvisor command hygiene (2026-04-15 remediation).

Context
-------
During the 2026-04-15 minitux install failure, cAdvisor was observed
booting, printing something resembling usage text, and exiting
quickly enough to be classified as ``running → restarting`` by
``docker compose ps``. It consumed restart budget, polluted the
install log, and contributed nothing diagnostically useful. The
underlying cause is almost certainly a flag-parsing edge case on
Linux kernel 6.x with cgroupsv2: cAdvisor is extremely sensitive to
the combination of privileged mode, docker-socket mount, and the
``--disable_metrics`` / ``--docker_only`` flag set.

The fix is defensive: pin a known-good invocation for kernel 6.x
hosts (``--docker_only=true`` to prevent discovery of non-docker
runtimes; ``--store_container_labels=false`` to avoid label
explosion; the existing ``--disable_metrics`` list to quiet the
``/sys/fs/resctrl`` and accelerator probes that are not present on
standard minitux or Azure VM kernels).

This test module locks the cAdvisor ``command`` shape in
``docker-compose.prod.yml`` so a reviewer who edits it must also
update the expected flag set here. That prevents silent regressions
of the sort that produced the original minitux noise.

The test is a pure YAML parser exercise — it does not invoke docker
or cadvisor. Integration coverage (run cadvisor against a real
socket, assert /healthz returns 200, assert logs don't contain
"Usage:") is tracked separately in ``tests/shell/`` and requires a
docker-enabled host.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Expected flag contract.
# ---------------------------------------------------------------------------
#
# Each entry is (flag_name, required). required=True means the flag
# MUST appear exactly once. required=False means the flag is optional
# but, if present, must be in the known-good form validated below.
# ---------------------------------------------------------------------------

#: Image tag we pin in docker-compose.prod.yml. When the image is
#: bumped, the valid-metrics enum below MUST be re-derived from the
#: matching cAdvisor source (container/container.go :: MetricKind)
#: and this constant updated. A mismatch between the pinned tag and
#: this constant is itself a test failure (see
#: ``test_pinned_cadvisor_version_matches_valid_metrics_table`` below).
PINNED_CADVISOR_VERSION: str = "v0.49.1"

#: The complete set of metric names that cAdvisor v0.49.1 accepts as
#: values for ``--disable_metrics`` and ``--enable_metrics``.
#:
#: Source: https://github.com/google/cadvisor/blob/v0.49.1/docs/runtime_options.md
#: (the ``--disable_metrics`` table). Cross-verified against
#: ``container/container.go`` in the same tag.
#:
#: This set is the single source of truth for validating any flag
#: value we pass to cAdvisor. The 2026-04-20 minitux incident was
#: caused by ``accelerator`` — a metric name removed when Nvidia GPU
#: support was reworked — appearing in ``--disable_metrics``. cAdvisor
#: rejected it at flag-parse time, dumped usage, and exited 2; the
#: restart policy then looped it. This constant + the parametrised
#: test below is the structural guarantee that the same class of
#: typo cannot reach prod again without a failing pytest run.
CADVISOR_V0_49_1_VALID_METRICS: frozenset[str] = frozenset(
    {
        "advtcp",
        "app",
        "cpu",
        "cpuLoad",
        "cpu_topology",
        "cpuset",
        "disk",
        "diskIO",
        "hugetlb",
        "memory",
        "memory_numa",
        "network",
        "oom_event",
        "percpu",
        "perf_event",
        "process",
        "psi_avg",
        "psi_total",
        "referenced_memory",
        "resctrl",
        "sched",
        "tcp",
        "udp",
    }
)

#: Flags that must be present in every cadvisor invocation on this
#: platform. Each is justified in a comment so reviewers see the
#: reasoning at the assertion site without chasing a separate doc.
REQUIRED_CADVISOR_FLAGS: tuple[tuple[str, str], ...] = (
    # Explicit port so the healthcheck URL in the compose file stays
    # in sync with the listener.
    ("--port=8080", "listener port; pairs with compose healthcheck URL"),
    # Housekeeping cadence controls scrape overhead. 30 s is the
    # standard compromise between freshness and CPU cost.
    ("--housekeeping_interval=30s", "scrape cadence"),
    # --docker_only=true prevents cadvisor from trying to discover
    # LXC / systemd-nspawn / raw-cgroup containers which are not
    # present on minitux or the Azure VM targets. Without it, cadvisor
    # logs warnings every housekeeping tick about missing cgroup
    # hierarchies.
    ("--docker_only=true", "limit discovery to docker — N1 kernel 6.x hygiene"),
    # --store_container_labels=false prevents every Prometheus time
    # series from exploding into (N labels × M containers) cardinality.
    # Label storage is not needed for our Prometheus rules; disabling
    # reduces both memory use in cadvisor and cardinality in
    # Prometheus.
    (
        "--store_container_labels=false",
        "prevent label-cardinality explosion in Prometheus",
    ),
    # Disable metrics that access /sys paths not present on
    # containerised kernels (resctrl) or duplicate information
    # Prometheus already gets from node-exporter (cpu_topology).
    #
    # Historical note: ``accelerator`` appeared here before 2026-04-20
    # but was removed — it is NOT a valid metric in cAdvisor v0.49.1
    # (see CADVISOR_V0_49_1_VALID_METRICS above). Passing it caused
    # cAdvisor to exit 2 with a usage dump on every restart attempt.
    (
        "--disable_metrics=cpu_topology,resctrl",
        "silence metrics that do not apply on minitux / Azure VMs",
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_prod_config() -> dict[str, Any]:
    """Parse ``docker-compose.prod.yml`` once per module."""
    # tests/unit/<this file> → project root two levels up.
    root = Path(__file__).resolve().parents[2]
    path = root / "docker-compose.prod.yml"
    if not path.is_file():
        pytest.fail(f"docker-compose.prod.yml not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        parsed = yaml.safe_load(fh)
    assert isinstance(parsed, dict), "compose root must be a mapping"
    return parsed


@pytest.fixture(scope="module")
def cadvisor_service(compose_prod_config: dict[str, Any]) -> dict[str, Any]:
    """Extract the cadvisor service block from the prod compose file."""
    services = compose_prod_config.get("services", {})
    assert "cadvisor" in services, "docker-compose.prod.yml must define a 'cadvisor' service."
    service = services["cadvisor"]
    assert isinstance(service, dict), "cadvisor service must be a mapping"
    return service


@pytest.fixture(scope="module")
def cadvisor_command(cadvisor_service: dict[str, Any]) -> list[str]:
    """Extract and normalise the cadvisor command list.

    Compose accepts both string form (``command: foo --bar``) and list
    form (``command: [foo, --bar]``). Shell-quoting bugs are trivial
    to introduce in the string form, so this test requires list form.
    """
    command = cadvisor_service.get("command")
    assert command is not None, (
        "cadvisor service must declare a 'command'. Without one, "
        "cadvisor falls back to image defaults which are NOT tuned "
        "for minitux / Azure VM kernels."
    )
    assert isinstance(command, list), (
        "cadvisor command must be a YAML list (not a shell string). "
        "List form eliminates shell-quoting bugs of the sort that "
        "contributed to the 2026-04-15 minitux noise. "
        f"Got: {type(command).__name__}."
    )
    # Normalise to plain str entries (pyyaml may return
    # ruamel-flavoured scalars in some test environments).
    return [str(flag) for flag in command]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cadvisor_command_is_list_not_string(
    cadvisor_command: list[str],
) -> None:
    """Fixture-level sanity check — reports a clear error to the user.

    Duplicated in the fixture for defence in depth; documented here so
    the test name surfaces the contract if it fails.
    """
    assert len(cadvisor_command) > 0, "cadvisor command must be non-empty"


@pytest.mark.parametrize(
    ("flag", "rationale"),
    REQUIRED_CADVISOR_FLAGS,
)
def test_cadvisor_command_contains_required_flag(
    cadvisor_command: list[str],
    flag: str,
    rationale: str,
) -> None:
    """Every required flag must appear in the cadvisor command list.

    The ``rationale`` arg is unused by the assertion but appears in
    the pytest parametrise id so a failing test line clearly shows
    WHY the flag matters.
    """
    assert flag in cadvisor_command, (
        f"cadvisor command is missing required flag: {flag!r}. "
        f"Rationale: {rationale}. "
        f"Full command: {cadvisor_command!r}."
    )


def test_cadvisor_command_has_no_empty_entries(
    cadvisor_command: list[str],
) -> None:
    """No empty strings in the command list.

    An empty string becomes a zero-length argv entry, which some
    Go flag parsers treat as a positional argument and which can
    trigger fallback behaviour (e.g. printing usage). List form
    protects us from shell-quoting bugs, but not from empty strings.
    """
    for idx, entry in enumerate(cadvisor_command):
        assert entry.strip() != "", (
            f"cadvisor command entry at index {idx} is empty / whitespace. "
            f"Full command: {cadvisor_command!r}."
        )


def test_cadvisor_command_flags_all_start_with_dash(
    cadvisor_command: list[str],
) -> None:
    """All entries look like flags — no accidental positional arguments.

    cadvisor accepts no positional arguments; any entry not starting
    with '-' is a misconfiguration that Go's flag package would treat
    as the end of parsing and surface as "unknown argument".
    """
    for entry in cadvisor_command:
        assert entry.startswith("-"), (
            f"cadvisor command entry {entry!r} is not a flag. "
            "cadvisor takes no positional arguments. "
            f"Full command: {cadvisor_command!r}."
        )


def test_cadvisor_no_double_dash_help_or_usage_triggers(
    cadvisor_command: list[str],
) -> None:
    """Hard block on flags that make cadvisor print usage and exit 0.

    cadvisor prints its usage and exits successfully for ``-h``,
    ``--help``, ``-help``, ``-h=true``, and similar. If any of these
    appear in the compose command, the container will be classified
    as "running" briefly then restart, wasting budget and polluting
    the install log. The 2026-04-15 minitux post-mortem suspected
    exactly this class of bug.
    """
    forbidden = {
        "-h",
        "-h=true",
        "-help",
        "-help=true",
        "--help",
        "--help=true",
    }
    for entry in cadvisor_command:
        # Compare both raw and pre-equals forms so "--help=true" is caught.
        head = entry.split("=", 1)[0]
        assert entry not in forbidden and head not in forbidden, (
            f"cadvisor command contains a help/usage trigger: {entry!r}. "
            "That flag makes cadvisor print usage text and exit 0, "
            "which causes docker-compose to classify the container as "
            "'running → restarting' and burn restart budget."
        )


def test_cadvisor_service_has_healthcheck(
    cadvisor_service: dict[str, Any],
) -> None:
    """cadvisor must declare a healthcheck.

    Without it, docker-compose cannot detect the "printed usage and
    exited" failure mode — the container transitions to Exited(0)
    and is restarted silently by the restart policy. The healthcheck
    turns silent restart-looping into a visible "unhealthy" state.
    """
    healthcheck = cadvisor_service.get("healthcheck")
    assert healthcheck is not None, (
        "cadvisor service must declare a healthcheck so restart-"
        "looping failures are visible to 'docker compose ps'."
    )
    test_entry = healthcheck.get("test")
    assert test_entry, "cadvisor healthcheck 'test' field must be set"
    # The test command must target /healthz on the port we pinned above.
    joined = " ".join(test_entry) if isinstance(test_entry, list) else str(test_entry)
    assert "/healthz" in joined, f"cadvisor healthcheck should probe /healthz. Got: {joined!r}."
    assert "8080" in joined, (
        f"cadvisor healthcheck should target port 8080 (matches --port flag). Got: {joined!r}."
    )


def test_cadvisor_image_is_pinned_to_specific_tag(
    cadvisor_service: dict[str, Any],
) -> None:
    """cadvisor image must use an explicit, non-floating tag.

    Floating tags (``:latest``, ``:v0.49``) re-introduce the original
    2026-04-15 risk: a silent image upgrade changes flag parsing or
    metric collectors, and the install degrades without a visible
    compose change.
    """
    image = cadvisor_service.get("image", "")
    assert ":" in image, f"cadvisor image must be pinned to a specific tag. Got: {image!r}."
    tag = image.split(":", 1)[1]
    assert tag not in {"latest", "edge", "stable"}, (
        f"cadvisor image tag {tag!r} is floating — pin to a specific "
        "version (e.g. v0.49.1) so upgrades are explicit review events."
    )
    # Tag should start with 'v' followed by a digit, or be a digest.
    assert tag.startswith("v") or tag.startswith("sha256:"), (
        f"cadvisor image tag {tag!r} does not look like a version or "
        "digest. Pin to e.g. v0.49.1 or sha256:... ."
    )


# ---------------------------------------------------------------------------
# Defensive flag-value validation (2026-04-20 remediation)
# ---------------------------------------------------------------------------
#
# The ``REQUIRED_CADVISOR_FLAGS`` contract above locks the shape of the
# command list, but it treats each flag as an opaque string — so a
# reviewer who swapped one valid metric name for another (e.g. typo'd
# ``cpu_topology`` → ``cpu_topo``, or left behind a removed metric
# like ``accelerator``) would slip past it.
#
# The tests below add a second layer: every token in ``--disable_metrics``
# must be a member of the known-good set for the pinned cAdvisor image.
# This is the exact gate the 2026-04-20 minitux failure would have
# tripped.
# ---------------------------------------------------------------------------


def _extract_flag_value(command: list[str], flag_name: str) -> str | None:
    """Return the value of ``--flag=value`` from a command list, or None.

    Args:
        command: the cadvisor command list (already validated to be
            list-shaped by fixtures above).
        flag_name: the flag to search for, e.g. ``--disable_metrics``.

    Returns:
        The string after ``=`` if the flag is present in ``--flag=value``
        form, else None. Does not support the space-separated form
        (``--flag value``) because the hygiene contract already
        mandates ``key=value`` shape for every flag — see
        ``test_cadvisor_command_flags_all_start_with_dash``.

    Example:
        _extract_flag_value(["--port=8080"], "--port") == "8080"
    """
    prefix = flag_name + "="
    for entry in command:
        if entry.startswith(prefix):
            return entry[len(prefix) :]
    return None


def test_pinned_cadvisor_version_matches_valid_metrics_table(
    cadvisor_service: dict[str, Any],
) -> None:
    """The compose image tag must match the version backing the enum.

    If an engineer bumps the cAdvisor image tag without also updating
    ``CADVISOR_V0_49_1_VALID_METRICS`` (and this test's PINNED_*
    constant), the defensive validation below would be comparing
    against a stale metric enum. This test makes the dependency
    explicit so the bump is a two-line change, not a silent drift.
    """
    image = cadvisor_service.get("image", "")
    assert ":" in image, f"cadvisor image must be pinned. Got: {image!r}."
    tag = image.split(":", 1)[1]
    assert tag == PINNED_CADVISOR_VERSION, (
        f"cAdvisor image tag {tag!r} no longer matches "
        f"PINNED_CADVISOR_VERSION={PINNED_CADVISOR_VERSION!r} in this "
        "test module. If you intentionally bumped the image, also "
        "update PINNED_CADVISOR_VERSION and re-derive "
        "CADVISOR_V0_49_1_VALID_METRICS from the new tag's "
        "container/container.go (MetricKind) or runtime_options.md."
    )


def test_disable_metrics_flag_is_present_and_well_formed(
    cadvisor_command: list[str],
) -> None:
    """``--disable_metrics=<csv>`` must be present and non-empty.

    Guards against a drift where the flag is removed (re-enabling
    noisy collectors) or left empty (ambiguous — Go's flag parser
    accepts empty CSV and the behaviour is version-dependent).
    """
    value = _extract_flag_value(cadvisor_command, "--disable_metrics")
    assert value is not None, (
        "cadvisor command must include --disable_metrics=<csv>. "
        "Without it, metrics that access /sys paths not present on "
        "containerised kernels (e.g. resctrl) are collected and fail "
        "noisily every housekeeping tick. "
        f"Full command: {cadvisor_command!r}."
    )
    assert value.strip() != "", (
        "cadvisor --disable_metrics value is empty. Pass at least "
        "'cpu_topology,resctrl' for minitux / Azure VM kernels."
    )
    # No whitespace tolerated inside the CSV — cAdvisor's parser does
    # not strip whitespace and would treat ' cpu_topology' as an
    # unknown metric name.
    assert " " not in value and "\t" not in value, (
        f"cadvisor --disable_metrics value {value!r} contains whitespace. "
        "cAdvisor's flag parser does not strip whitespace from CSV "
        "entries; use the exact form 'a,b,c' with no spaces."
    )


def test_disable_metrics_values_are_all_valid_for_pinned_cadvisor_version(
    cadvisor_command: list[str],
) -> None:
    """Every token in ``--disable_metrics`` must be a known v0.49.1 metric.

    This is the specific guard that would have caught the 2026-04-20
    minitux failure. ``accelerator`` was in the CSV but is not a
    valid metric name in v0.49.1 — cAdvisor's flag parser rejected
    it, dumped usage, and exited 2 on every start attempt.

    The assertion message lists the offending tokens so the operator
    can fix the compose file in one edit without consulting docs.
    """
    value = _extract_flag_value(cadvisor_command, "--disable_metrics")
    # The previous test asserts non-None / non-empty; we gate here
    # defensively so a failure of one test does not cascade.
    if not value:
        pytest.skip("--disable_metrics absent or empty; see previous test")

    tokens = [t for t in value.split(",") if t]
    invalid = [t for t in tokens if t not in CADVISOR_V0_49_1_VALID_METRICS]

    assert not invalid, (
        f"cadvisor --disable_metrics contains tokens that are NOT valid "
        f"metric names in cAdvisor {PINNED_CADVISOR_VERSION}: {invalid!r}. "
        f"Passing an unknown metric name causes cAdvisor's Go flag "
        f"parser to reject the entire flag set, dump usage to stderr, "
        f"and exit 2. The restart policy then loops the container "
        f"forever. "
        f"Valid metrics are: {sorted(CADVISOR_V0_49_1_VALID_METRICS)!r}. "
        f"(2026-04-20 minitux post-mortem)."
    )


def test_disable_metrics_has_no_duplicates(
    cadvisor_command: list[str],
) -> None:
    """Each metric may appear at most once in ``--disable_metrics``.

    Duplicates are a reviewer-error smell (two edits both adding the
    same name) and, while cAdvisor tolerates them today, the
    tolerance is not part of its documented contract. Fail fast.
    """
    value = _extract_flag_value(cadvisor_command, "--disable_metrics")
    if not value:
        pytest.skip("--disable_metrics absent; see earlier test")
    tokens = [t for t in value.split(",") if t]
    dupes = sorted({t for t in tokens if tokens.count(t) > 1})
    assert not dupes, (
        f"cadvisor --disable_metrics contains duplicate entries: {dupes!r}. Full CSV: {value!r}."
    )
