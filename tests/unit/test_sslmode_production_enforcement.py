"""
Unit tests for C1 — sslmode production enforcement (2026-04-15 remediation).

Context
-------
The minitux install post-mortem found a DATABASE_URL containing
``?sslmode=prefer``. libpq's ``prefer`` means "try SSL; fall back to
plaintext without error if negotiation fails". In a production
deployment that is functionally indistinguishable from ``sslmode=disable``
when the server's SSL negotiation breaks — credentials and trading data
would travel in plaintext and the application would not know. The legacy
startup check (H1.7) only rejected DATABASE_URL strings that lacked
``sslmode=`` entirely; an explicit but weak value (``disable``,
``allow``, ``prefer``) slipped through.

This suite locks in the tightened contract:

- In ``ENVIRONMENT=production``, the three strict libpq values
  (``require``, ``verify-ca``, ``verify-full``) are accepted.
- In ``ENVIRONMENT=production``, the three weak libpq values
  (``disable``, ``allow``, ``prefer``) are rejected with a
  ``RuntimeError`` whose message names the accepted values so the
  operator knows how to fix it.
- In non-production environments (``development``, ``staging``,
  ``test``), all six values are accepted. Local dev must remain
  frictionless and ``minitux`` is designated development per
  ``project_environment_designation`` memory.

The test module is scoped narrowly: it exercises ``_validate_startup_secrets``
directly against a synthesised environment, so it runs in milliseconds
and does not require a database.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# libpq sslmode classification — the source of truth for this test module.
# ---------------------------------------------------------------------------
#
# libpq defines exactly six sslmode values. Any change to this mapping is a
# security-relevant decision and MUST be reviewed alongside the production
# enforcement policy in services/api/main.py::_validate_startup_secrets.
#
# Reference: https://www.postgresql.org/docs/current/libpq-ssl.html
# ---------------------------------------------------------------------------

#: Values that do NOT guarantee an encrypted connection. Each one either
#: refuses SSL outright (``disable``), attempts it only if the server
#: initiates (``allow``), or silently falls back to plaintext when SSL
#: negotiation fails (``prefer``).
WEAK_SSLMODES: tuple[str, ...] = ("disable", "allow", "prefer")

#: Values that guarantee an encrypted connection and (for the last two)
#: additional server-identity verification.
STRICT_SSLMODES: tuple[str, ...] = ("require", "verify-ca", "verify-full")

#: Environments that must enforce strict sslmode. Kept as a frozenset so
#: ``in`` checks are clear at call sites.
PRODUCTION_ENVIRONMENTS: frozenset[str] = frozenset({"production"})

#: Environments in which all six values are accepted. ``minitux`` is tagged
#: ``development`` (see auto-memory), so ``development`` must be lenient.
NON_PRODUCTION_ENVIRONMENTS: tuple[str, ...] = (
    "development",
    "staging",
    "test",
)


def _pg_url(sslmode: str) -> str:
    """Build a canonical PostgreSQL DSN carrying the given sslmode value.

    The DSN uses a synthetic host/user/password combination — the test
    does not open a network connection; ``_validate_startup_secrets``
    only inspects the URL string.
    """
    return f"postgresql://u:p@host:5432/db?sslmode={sslmode}"


# ---------------------------------------------------------------------------
# Production — strict sslmodes are accepted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sslmode", STRICT_SSLMODES)
def test_production_accepts_strict_sslmode(sslmode: str) -> None:
    """Every strict libpq sslmode value must pass production validation.

    Rationale:
        ``require``, ``verify-ca``, and ``verify-full`` all guarantee an
        encrypted channel. Blocking any of them would force operators to
        downgrade their posture to pass startup — the opposite of the
        intended policy.
    """
    from services.api.main import _validate_startup_secrets

    with patch.dict(
        os.environ,
        {
            "ENVIRONMENT": "production",
            "DATABASE_URL": _pg_url(sslmode),
            "JWT_SECRET_KEY": "a" * 64,
        },
        clear=False,
    ):
        # Must not raise. Any raise here is a regression.
        _validate_startup_secrets()


# ---------------------------------------------------------------------------
# Production — weak sslmodes are rejected with an instructive message.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sslmode", WEAK_SSLMODES)
def test_production_rejects_weak_sslmode(sslmode: str) -> None:
    """Every weak libpq sslmode must raise in production with a fixable message.

    The message MUST:
      1. Name the offending sslmode so the operator can grep for it in
         compose/secret manifests.
      2. Enumerate the allowed values so there is no ambiguity about the fix.
    """
    from services.api.main import _validate_startup_secrets

    with (
        patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "DATABASE_URL": _pg_url(sslmode),
                "JWT_SECRET_KEY": "a" * 64,
            },
            clear=False,
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        _validate_startup_secrets()

    message = str(exc_info.value)
    # Names the bad value explicitly — so grep -F "$(kubectl get secret …)" hits.
    assert f"sslmode={sslmode}" in message, (
        f"Error must name the offending sslmode value. Got: {message!r}"
    )
    # Enumerates the acceptable values so the operator can copy/paste a fix.
    for strict in STRICT_SSLMODES:
        assert strict in message, (
            f"Error must enumerate allowed value {strict!r}. Got: {message!r}"
        )


# ---------------------------------------------------------------------------
# Non-production environments — all six values are accepted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("environment", NON_PRODUCTION_ENVIRONMENTS)
@pytest.mark.parametrize("sslmode", WEAK_SSLMODES + STRICT_SSLMODES)
def test_non_production_accepts_all_sslmodes(
    environment: str,
    sslmode: str,
) -> None:
    """Non-production environments must accept any libpq sslmode value.

    Rationale:
        Local development against a plaintext Postgres in docker-compose
        is the canonical minitux workflow. Blocking ``sslmode=disable``
        in development would break the inner loop for zero security
        benefit (the Postgres container is on a private docker network).
        ``test`` remains the most permissive: it uses the test-mode
        sentinel and returns early from ``_validate_startup_secrets``.
    """
    from services.api.main import _validate_startup_secrets

    env_patch = {
        "ENVIRONMENT": environment,
        "DATABASE_URL": _pg_url(sslmode),
    }
    # Staging/development go through the full validator path, which
    # also checks JWT_SECRET_KEY. Test short-circuits, so JWT is not
    # strictly required — we set it anyway to keep the parametrise
    # matrix symmetric and easy to read.
    if environment != "test":
        env_patch["JWT_SECRET_KEY"] = "a" * 64

    with patch.dict(os.environ, env_patch, clear=False):
        # Must not raise. The sslmode gate is production-only.
        _validate_startup_secrets()


# ---------------------------------------------------------------------------
# Regression guard — exact minitux scenario.
# ---------------------------------------------------------------------------


def test_production_rejects_sslmode_prefer_named_regression() -> None:
    """Named regression guard for the exact 2026-04-15 minitux scenario.

    The installer saw ``?sslmode=prefer`` in DATABASE_URL and proceeded
    to launch the api container. If a future refactor weakens the
    policy and re-admits ``prefer`` under ``ENVIRONMENT=production``,
    this test will trip by name so the reviewer connects it to the
    original incident.

    See ``docs/remediation/2026-04-15-minitux-install-failure.md``
    (Commit 8, C1).
    """
    from services.api.main import _validate_startup_secrets

    with (
        patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "DATABASE_URL": _pg_url("prefer"),
                "JWT_SECRET_KEY": "a" * 64,
            },
            clear=False,
        ),
        pytest.raises(RuntimeError, match=r"sslmode=prefer"),
    ):
        _validate_startup_secrets()


# ---------------------------------------------------------------------------
# Non-PostgreSQL URLs — the sslmode gate MUST NOT fire.
# ---------------------------------------------------------------------------


def test_production_sqlite_url_bypasses_sslmode_gate() -> None:
    """A SQLite DATABASE_URL must not trigger the sslmode gate.

    The sslmode check is a libpq concept. Applying it to sqlite:// URLs
    would reject every test fixture in the repo. A separate production
    guard (in services/api/db.py::_resolve_database_url) already rejects
    SQLite in production; that's the correct layer for that policy.
    """
    from services.api.main import _validate_startup_secrets

    with patch.dict(
        os.environ,
        {
            "ENVIRONMENT": "production",
            "DATABASE_URL": "sqlite:///./test.db",
            "JWT_SECRET_KEY": "a" * 64,
        },
        clear=False,
    ):
        # Must not raise — the sslmode code path must be skipped entirely
        # for non-postgresql schemes.
        _validate_startup_secrets()
