"""
Unit tests for N3 — PostgreSQL locale warning elimination (2026-04-15 remediation).

Context
-------
During the 2026-04-15 minitux install log review, the postgres container
produced::

    WARNING: the locale "en_US.UTF-8" is not installed

on every boot. The ``postgres:15-alpine`` base image ships with the
Alpine ``musl`` libc, which does not bundle the ``en_US.UTF-8`` locale.
initdb inherits ``LANG`` from the container environment; when ``LANG``
is unset, initdb falls back to a locale that is not present, and PG
emits the warning on every startup.

The warning is harmless — we use UTF-8 byte-ordered comparisons
throughout the codebase and do not depend on ICU collation — but it
pollutes the install log and trains operators to ignore startup noise.
That behaviour masked several higher-severity issues during the
2026-04-15 minitux install (see P-track in the remediation doc).

Fix
---
Pin the postgres container environment to ``C.UTF-8`` explicitly:

  1. ``LANG=C.UTF-8`` — Alpine ships this locale; initdb uses it as the
     default collation, encoding, and ctype unless overridden.
  2. ``POSTGRES_INITDB_ARGS`` includes ``--locale=C.UTF-8`` — belt-and-
     braces for initdb so the choice is explicit rather than implicit
     from the environment. Only read on first-run initdb; no-op for
     already-initialised data directories.

``C.UTF-8`` is strictly weaker than ``en_US.UTF-8`` only in case-
insensitive locale-aware comparisons, none of which FXLab uses. All
identifiers compare byte-wise and numeric collation is unaffected.

This test module parses ``docker-compose.prod.yml`` and pins the
postgres environment so a reviewer cannot silently regress the fix
(e.g. by removing the ``LANG`` line or setting ``POSTGRES_INITDB_ARGS``
to a non-C locale).

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------
#
# These encode the N3 policy exactly once. If the policy changes (e.g.
# we migrate to a debian-based postgres image that ships en_US.UTF-8),
# reviewers update the constants here and the test failures surface
# every config site that needs to be touched.

#: Required container locale. ``C.UTF-8`` is the Alpine-available
#: UTF-8 locale with byte-ordered collation. Case-insensitive
#: locale-aware comparisons are NOT used anywhere in FXLab.
_REQUIRED_LANG = "C.UTF-8"

#: The fragment that must appear inside ``POSTGRES_INITDB_ARGS`` so
#: initdb uses the same locale explicitly on first boot.
_REQUIRED_INITDB_LOCALE_FLAG = "--locale=C.UTF-8"

#: Locales that would re-introduce the warning if accidentally set.
#: Include both the exact string observed in the minitux log and a
#: handful of close misspellings that a tired operator might type.
_FORBIDDEN_LOCALES: tuple[str, ...] = (
    "en_US.UTF-8",
    "en_US.utf8",
    "en_US.UTF8",
    "en_US",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_prod_config() -> dict[str, Any]:
    """Parse ``docker-compose.prod.yml`` once per module.

    The file lives at the project root, two parents up from this test.
    """
    root = Path(__file__).resolve().parents[2]
    path = root / "docker-compose.prod.yml"
    if not path.is_file():
        pytest.fail(f"docker-compose.prod.yml not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        parsed = yaml.safe_load(fh)
    assert isinstance(parsed, dict), "compose root must be a mapping"
    return parsed


@pytest.fixture(scope="module")
def postgres_service(compose_prod_config: dict[str, Any]) -> dict[str, Any]:
    """Extract the postgres service block from the prod compose file."""
    services = compose_prod_config.get("services", {})
    assert "postgres" in services, (
        "docker-compose.prod.yml must define a 'postgres' service."
    )
    service = services["postgres"]
    assert isinstance(service, dict), "postgres service must be a mapping"
    return service


@pytest.fixture(scope="module")
def postgres_environment(postgres_service: dict[str, Any]) -> dict[str, str]:
    """Return postgres ``environment`` as a ``KEY=VALUE`` dict.

    Compose accepts both list form (``- KEY=VALUE``) and mapping form.
    We normalise to a dict so test assertions are shape-agnostic.
    Entries without an ``=`` are skipped (compose treats them as
    "inherit from host" which is not used anywhere in this file).
    """
    env = postgres_service.get("environment")
    assert env is not None, (
        "postgres service must declare an 'environment' block. "
        "Without it, initdb inherits the container's default locale "
        "(en_US.UTF-8) and emits the N3 warning on every boot."
    )

    # List form — "KEY=VALUE" per entry.
    if isinstance(env, list):
        pairs: dict[str, str] = {}
        for entry in env:
            entry_str = str(entry)
            if "=" in entry_str:
                key, value = entry_str.split("=", 1)
                pairs[key] = value
        return pairs

    # Mapping form — compose preserves scalar values as-is.
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}

    pytest.fail(
        f"postgres environment has unexpected type {type(env).__name__}. "
        "Must be list or mapping."
    )


# ---------------------------------------------------------------------------
# LANG environment variable
# ---------------------------------------------------------------------------


def test_postgres_environment_declares_lang(
    postgres_environment: dict[str, str],
) -> None:
    """The postgres ``environment`` block must declare ``LANG``.

    Without ``LANG``, the container falls back to initdb's internal
    default, which on Alpine is not installed. Declaring ``LANG``
    explicitly is the minimal structural guarantee that the warning
    cannot return.
    """
    assert "LANG" in postgres_environment, (
        "postgres service must set LANG in its environment block. "
        f"Current keys: {sorted(postgres_environment.keys())}."
    )


def test_postgres_lang_is_C_UTF_8(
    postgres_environment: dict[str, str],
) -> None:
    """``LANG`` must be exactly ``C.UTF-8``.

    Any other locale either is not available in the Alpine base image
    (re-introducing the warning) or changes collation semantics in a
    way no one on the team has reviewed.
    """
    actual = postgres_environment.get("LANG", "")
    assert actual == _REQUIRED_LANG, (
        f"postgres LANG must be {_REQUIRED_LANG!r} (got {actual!r}). "
        "C.UTF-8 is the Alpine-available UTF-8 locale and matches "
        "our byte-ordered-comparison invariants."
    )


@pytest.mark.parametrize("forbidden", _FORBIDDEN_LOCALES)
def test_postgres_lang_is_not_a_forbidden_locale(
    postgres_environment: dict[str, str],
    forbidden: str,
) -> None:
    """``LANG`` must not be any locale known to be absent on Alpine.

    This is a named regression guard: the exact string observed in the
    2026-04-15 minitux install log is ``en_US.UTF-8``. Listing the
    close misspellings catches the tired-operator case as well.
    """
    actual = postgres_environment.get("LANG", "")
    assert actual != forbidden, (
        f"postgres LANG is set to {forbidden!r}, which is not "
        "installed on postgres:15-alpine and re-introduces the "
        "N3 locale warning. Use 'C.UTF-8' instead."
    )


# ---------------------------------------------------------------------------
# POSTGRES_INITDB_ARGS
# ---------------------------------------------------------------------------


def test_postgres_initdb_args_pins_locale_explicitly(
    postgres_environment: dict[str, str],
) -> None:
    """``POSTGRES_INITDB_ARGS`` must include ``--locale=C.UTF-8``.

    Even with ``LANG=C.UTF-8`` set, explicitly passing
    ``--locale=C.UTF-8`` to initdb is belt-and-braces: the choice is
    durable in the cluster's ``pg_database`` entries rather than
    dependent on the container's process environment. It is a no-op
    on subsequent boots because initdb only runs on first launch.
    """
    initdb_args = postgres_environment.get("POSTGRES_INITDB_ARGS", "")
    assert _REQUIRED_INITDB_LOCALE_FLAG in initdb_args, (
        f"POSTGRES_INITDB_ARGS must contain {_REQUIRED_INITDB_LOCALE_FLAG!r}. "
        f"Current value: {initdb_args!r}."
    )


def test_postgres_initdb_args_preserves_auth_host(
    postgres_environment: dict[str, str],
) -> None:
    """The existing ``--auth-host=scram-sha-256`` flag must survive.

    Regression guard: the initial pre-N3 compose file carried
    ``--auth-host=scram-sha-256`` to force SCRAM password hashing
    for host connections. The N3 edit adds ``--locale=C.UTF-8``
    alongside it; this test confirms the auth flag was not lost.
    """
    initdb_args = postgres_environment.get("POSTGRES_INITDB_ARGS", "")
    assert "--auth-host=scram-sha-256" in initdb_args, (
        "POSTGRES_INITDB_ARGS must still contain --auth-host=scram-sha-256. "
        f"Current value: {initdb_args!r}."
    )


@pytest.mark.parametrize("forbidden", _FORBIDDEN_LOCALES)
def test_postgres_initdb_args_does_not_set_forbidden_locale(
    postgres_environment: dict[str, str],
    forbidden: str,
) -> None:
    """``POSTGRES_INITDB_ARGS`` must not pin a locale absent on Alpine.

    A reviewer could accidentally replace ``--locale=C.UTF-8`` with
    ``--locale=en_US.UTF-8`` thinking it is "more correct". That change
    would silently break first-boot initdb on the alpine base image.
    """
    initdb_args = postgres_environment.get("POSTGRES_INITDB_ARGS", "")
    # Match the locale only as a whole word after --locale= so
    # substrings like "en_US.UTF-8" inside a comment don't trip us.
    pattern = re.compile(
        rf"--locale={re.escape(forbidden)}(?:\s|$)"
    )
    assert not pattern.search(initdb_args), (
        f"POSTGRES_INITDB_ARGS sets --locale={forbidden!r}, which is "
        "not installed on postgres:15-alpine. Use --locale=C.UTF-8."
    )


# ---------------------------------------------------------------------------
# Image pin — ensures the Alpine assumption remains valid.
# ---------------------------------------------------------------------------


def test_postgres_image_is_alpine_based(
    postgres_service: dict[str, Any],
) -> None:
    """The postgres image must remain an Alpine tag.

    The N3 fix assumes Alpine's ``musl`` libc locale set (``C.UTF-8``
    is present; ``en_US.UTF-8`` is not). If the base image changes
    to a Debian tag later, the locale contract needs re-review and
    this test should be updated deliberately, not as a drive-by.
    """
    image = str(postgres_service.get("image", ""))
    assert image, "postgres service must declare an image"
    assert "-alpine" in image, (
        f"postgres image {image!r} is not an alpine tag. "
        "N3 locale fix assumes Alpine's musl libc; if you migrate to "
        "a debian base image, update tests/unit/test_postgres_locale_hygiene.py "
        "and confirm en_US.UTF-8 is bundled."
    )


def test_postgres_image_is_pinned_to_specific_version(
    postgres_service: dict[str, Any],
) -> None:
    """The postgres image tag must be a concrete version, not floating.

    Defence-in-depth against ``:latest`` / ``:alpine`` floating tags:
    an unexpected upgrade could silently flip the locale defaults and
    drift from what N3 pinned. Pin to ``postgres:<major>-alpine`` or
    narrower so upgrades are deliberate.
    """
    image = str(postgres_service.get("image", ""))
    assert ":" in image, (
        f"postgres image must be pinned to a tag. Got: {image!r}."
    )
    tag = image.split(":", 1)[1]
    assert tag not in {"latest", "alpine", "stable", "edge"}, (
        f"postgres image tag {tag!r} is floating — pin to a specific "
        "major version (e.g. 15-alpine or 16-alpine)."
    )
    # Must begin with a digit so we can tell "15-alpine" from "alpine".
    assert tag[0].isdigit(), (
        f"postgres image tag {tag!r} does not begin with a version "
        "number. Pin to e.g. 15-alpine."
    )


# ---------------------------------------------------------------------------
# Named regression guard — exact 2026-04-15 minitux symptom.
# ---------------------------------------------------------------------------


def test_postgres_locale_named_regression_2026_04_15() -> None:
    """Named regression guard for the exact minitux symptom.

    The install log contained the line::

        WARNING: the locale "en_US.UTF-8" is not installed

    If a future edit reverts the fix (removes LANG, or sets it to
    ``en_US.UTF-8``, or drops ``--locale=C.UTF-8`` from
    ``POSTGRES_INITDB_ARGS``), the tests above will fail first. This
    test exists as a named landing-point so a reviewer grepping for
    ``2026-04-15`` finds every regression guard for the incident.

    See ``docs/remediation/2026-04-15-minitux-install-failure.md``
    (Commit 12, N3).
    """
    # Intentionally empty body — this test documents the existence of
    # the regression guard by name; the enforcement lives in the
    # tests above. Keeping it as a no-op avoids double-asserting the
    # same facts but ensures `pytest -k 2026_04_15` surfaces N3.
    assert True
