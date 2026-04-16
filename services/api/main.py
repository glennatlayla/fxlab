"""
FastAPI application entry point.

Responsibilities:
- Create and configure the FastAPI application instance.
- Register all route routers.
- Export service-layer stubs that are mocked in tests (get_run_results,
  get_readiness_report, submit_promotion_request, check_permission,
  audit_service).
- Define lifespan context manager for startup/shutdown logging.

Does NOT:
- Contain business logic.
- Perform I/O directly.

Example:
    from services.api.main import app
    # Use with TestClient or uvicorn.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Iterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from libs.contracts.errors import ConfigError
from services.api import metrics as metrics_module
from services.api.middleware.body_size import BodySizeLimitMiddleware
from services.api.middleware.client_source import ClientSourceMiddleware
from services.api.middleware.correlation import CorrelationIDMiddleware
from services.api.middleware.drain import DrainMiddleware
from services.api.middleware.idempotency import IdempotencyMiddleware
from services.api.middleware.rate_limit import RateLimitMiddleware
from services.api.middleware.security_headers import SecurityHeadersMiddleware
from services.api.routes import (
    admin,
    approvals,
    artifacts,
    audit,
    audit_export,
    auth,
    charts,
    compliance,
    data_certification,
    data_quality,
    deployments,
    drills,
    execution_analysis,
    execution_loop,
    exports,
    feed_health,
    feeds,
    governance,
    health,
    indicators,
    kill_switch,
    live,
    market_data,
    mobile_dashboard,
    observability,
    overrides,
    paper,
    parity,
    pnl,
    position_sizing,
    promotions,
    queues,
    readiness,
    reconciliation,
    research,
    risk,
    risk_alert,
    risk_analytics,
    runs,
    shadow,
    strategies,
    strategy_comparison,
    stress_test,
    symbol_lineage,
    ws_market_data,
    ws_positions,
)

logger = structlog.get_logger(__name__)

API_VERSION = "0.1.0-bootstrap"


# ---------------------------------------------------------------------------
# Lifespan — must be defined before FastAPI() is instantiated.
# ---------------------------------------------------------------------------


def _check_pydantic_core() -> None:
    """
    Detect whether pydantic-core's compiled Rust extension is loaded.

    The compiled extension is required for field constraint enforcement
    (min_length, pattern, ge/le, type coercion). When only the pure-Python
    stub is available, these constraints are silently skipped and manual
    HTTPException(422) workarounds must cover all critical validation paths.

    This check runs at startup so the problem surfaces immediately in logs
    rather than being discovered at runtime via data corruption.

    Note:
        The known root cause in this deployment is that the installed wheel
        was compiled for macOS (darwin) but the service runs on Linux.
        Fix: reinstall pydantic-core from PyPI using a Linux wheel:
            pip install --force-reinstall pydantic-core==<version>
    """
    try:
        from pydantic_core import SchemaValidator

        module = getattr(SchemaValidator, "__module__", "")
        if "stub" in module:
            logger.critical(
                "pydantic_core.stub_detected",
                component="startup",
                detail=(
                    "pydantic-core compiled Rust extension is NOT loaded. "
                    "Field constraints (min_length, pattern, ge/le) are "
                    "silently ignored on all Pydantic models. "
                    "Manual HTTPException(422) guards must cover all critical "
                    "validation paths. "
                    "Root cause: installed wheel is for macOS/darwin; "
                    "reinstall with a linux-aarch64 wheel to fix."
                ),
            )
        else:
            logger.info("pydantic_core.extension_loaded", module=module)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "pydantic_core.check_failed",
            error=str(exc),
            exc_info=True,
        )


@contextmanager
def _startup_phase(name: str, **fields: Any) -> Iterator[None]:
    """
    Instrument a discrete startup phase with structured begin/complete/failed logs.

    This exists so operators troubleshooting an install on a remote host
    (e.g. minitux) can identify EXACTLY which wiring block produced a
    failure, how long each phase took, and — on failure — the concrete
    error, all from structured logs without having to add print statements
    and redeploy.

    Each invocation emits:
    - ``startup.phase_begin``   at entry
    - ``startup.phase_complete`` at successful exit (with duration_ms)
    - ``startup.phase_failed``   on exception (with exc_info and duration_ms)

    The exception is re-raised after logging so the caller decides whether
    to let it abort startup or to catch it and degrade gracefully.

    Args:
        name: Phase name in snake_case (e.g. "live_execution_wiring").
        **fields: Additional structured fields to include on all three events.

    Yields:
        None. Use as a context manager.

    Example:
        with _startup_phase("redis_health_check", backend="redis"):
            verify_redis_connection(redis_url, timeout_seconds=5.0)
    """
    started = time.monotonic()
    logger.info(
        "startup.phase_begin",
        component="startup",
        phase=name,
        **fields,
    )
    try:
        yield
    except Exception:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.error(
            "startup.phase_failed",
            component="startup",
            phase=name,
            duration_ms=elapsed_ms,
            exc_info=True,
            **fields,
        )
        raise
    else:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "startup.phase_complete",
            component="startup",
            phase=name,
            duration_ms=elapsed_ms,
            **fields,
        )


def _log_runtime_versions() -> None:
    """
    Emit a single structured log line with the runtime versions of
    packages that have historically caused environment-specific issues.

    Specifically logs versions of pydantic, pydantic-core, SQLAlchemy,
    FastAPI, and structlog, plus the Python and platform strings. This
    is the fastest way to confirm from production logs whether a host
    has the expected dependency set — a prior incident in this codebase
    was caused by a macOS-built pydantic-core wheel landing on a Linux
    host.

    Also logs a non-secret snapshot of environment-shaping variables
    (ENVIRONMENT, DATABASE_URL scheme, REDIS_URL scheme, RATE_LIMIT_BACKEND,
    RECONCILIATION_INTERVAL_SECONDS) to confirm the deploy wired the
    intended configuration.
    """
    import platform
    import sys
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    def _safe_version(pkg: str) -> str:
        try:
            return _pkg_version(pkg)
        except PackageNotFoundError:
            return "not_installed"
        except Exception:  # pragma: no cover - defensive
            return "error"

    def _url_scheme(url: str) -> str:
        if not url:
            return "unset"
        return url.split("://", 1)[0] + "://..."

    logger.info(
        "startup.runtime_versions",
        component="startup",
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        machine=platform.machine(),
        pydantic=_safe_version("pydantic"),
        pydantic_core=_safe_version("pydantic_core"),
        sqlalchemy=_safe_version("SQLAlchemy"),
        fastapi=_safe_version("fastapi"),
        structlog=_safe_version("structlog"),
        alembic=_safe_version("alembic"),
        environment=os.environ.get("ENVIRONMENT", ""),
        database_url_scheme=_url_scheme(os.environ.get("DATABASE_URL", "")),
        redis_url_scheme=_url_scheme(os.environ.get("REDIS_URL", "")),
        rate_limit_backend=os.environ.get("RATE_LIMIT_BACKEND", "memory"),
        reconciliation_interval_seconds=os.environ.get("RECONCILIATION_INTERVAL_SECONDS", "300"),
        artifact_storage_backend=os.environ.get("ARTIFACT_STORAGE_BACKEND", "local"),
    )


#: Sentinel file path baked into production Docker images.
#: When this file exists and ENVIRONMENT=test, startup is blocked to prevent
#: accidental TEST_TOKEN bypass in production deployments.
_PRODUCTION_SENTINEL = "/app/.production-build"


# ---------------------------------------------------------------------------
# CORS origin policy (C2 — 2026-04-15 remediation)
# ---------------------------------------------------------------------------
#
# Production deployments must not accept cross-origin requests from plain
# HTTP origins or from private-IP / loopback literals. Both are vectors
# for MITM forgery of the ``Origin`` header. The escape hatch exists for
# legitimate controlled-rollout scenarios; it is deliberately noisy (an
# env var AND a written justification) so that bypasses are auditable.


class CorsOriginPolicyError(ConfigError):
    """
    Raised when the configured CORS allowlist violates production policy.

    Subclasses ``ConfigError`` (not ``RuntimeError``) so the lifespan
    error wrapper catches it alongside every other startup-time
    configuration failure and produces a deterministic ``sys.exit(3)``
    with a structured ``startup.aborted`` log event.

    Prior to the 2026-04-15 v2 remediation this class subclassed
    ``RuntimeError`` and was raised at module-import time. Both were
    wrong: the import-time raise bypassed the lifespan handler
    entirely, and the ``RuntimeError`` base class was not caught by
    the lifespan's ConfigError handler even if it had reached there.
    """


#: Minimum character length for the CORS plaintext-LAN justification.
#: Tuned to reject single-word rubber-stamp values ("ok", "approved")
#: while not being so high it encourages justifications-as-novels.
_CORS_JUSTIFICATION_MIN_CHARS = 20


def _host_is_private_or_loopback(host: str) -> str | None:
    """
    Classify ``host`` against RFC 1918 / 3927 / IPv6 link-local rules.

    Returns a short classification key (``"loopback"``, ``"private"``)
    if the host falls into one of the disallowed ranges, otherwise
    ``None``. The return value is consumed directly by the error
    message builder, so the strings are part of the policy contract
    and should not be changed without updating the test suite.

    Handles IPv6 bracket notation (``[::1]``) by stripping the
    brackets before resolving. IP literals outside the well-known
    private ranges return ``None`` — this function intentionally does
    not try to classify every RFC 5735 special-use range; we only
    want to catch the ranges that are plausibly used as CORS origins
    by a misconfigured deployment.
    """
    import ipaddress

    hostname = host.lower().strip()
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]

    # Named loopback — does not round-trip through ipaddress.
    if hostname in {"localhost", "localhost.localdomain"}:
        return "loopback"

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Not an IP literal — the policy has no opinion on named
        # public hosts beyond the scheme check handled elsewhere.
        return None

    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        # 169.254.0.0/16 and fe80::/10 — classified as "private" in
        # the error message because operators think of them as "LAN"
        # not "loopback".
        return "private"
    if addr.is_private:
        return "private"
    return None


def _classify_cors_origin(origin: str) -> str:
    """
    Classify a single CORS origin against the production policy.

    Returns one of:
        - ``"ok"``        — safe for production.
        - ``"scheme"``    — scheme is not ``https``.
        - ``"private"``   — host is a private-IP or link-local literal.
        - ``"loopback"``  — host is loopback (localhost / 127.0.0.1 / ::1).
        - ``"malformed"`` — origin cannot be parsed as a URL with a host.

    The classification key is stable — it is asserted by the test
    suite and forms part of the user-facing error message.

    Rationale for the classification order (scheme → host):
        The scheme check fires first so ``http://app.fxlab.example.com``
        is reported as a scheme violation, not a (missing) private-IP
        match. That is clearer for the operator.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(origin)
    except ValueError:
        return "malformed"

    if not parsed.scheme or not parsed.hostname:
        return "malformed"

    if parsed.scheme.lower() != "https":
        # Before returning "scheme", check whether the host is
        # loopback/private — those get a more specific classification
        # so the error names the real problem ("localhost is loopback"
        # is more actionable than "http is not https").
        host_reason = _host_is_private_or_loopback(parsed.hostname)
        if host_reason is not None:
            return host_reason
        return "scheme"

    host_reason = _host_is_private_or_loopback(parsed.hostname)
    if host_reason is not None:
        return host_reason

    return "ok"


def _validate_cors_origins(
    *,
    origins: list[str],
    environment: str,
    allow_plaintext_lan: bool,
    plaintext_justification: str,
) -> None:
    """
    Enforce the production CORS origin policy.

    Keyword-only signature so call sites read unambiguously —
    a positional ``bool`` + ``str`` pair is a classic bug magnet.

    Args:
        origins: The CORS allowlist, parsed from
            ``CORS_ALLOWED_ORIGINS``. An empty list is valid and
            produces no allowance.
        environment: The current ``ENVIRONMENT`` value. Only the
            literal string ``"production"`` triggers enforcement.
        allow_plaintext_lan: Value of
            ``CORS_ORIGINS_ALLOW_PLAINTEXT_LAN``. Must be paired with
            a non-trivial justification.
        plaintext_justification: Value of
            ``CORS_PLAINTEXT_JUSTIFICATION``. Logged at INFO during
            startup when the escape hatch is active so the bypass is
            auditable.

    Raises:
        CorsOriginPolicyError: In production, when any origin is
            weak and the escape hatch is either not set or not paired
            with a valid justification. The message names the first
            offending origin and the escape-hatch variable.
    """
    if environment != "production":
        return

    if allow_plaintext_lan:
        # Escape hatch is engaged — validate the justification and
        # let any origin shape through. The caller (startup code)
        # is responsible for writing the justification into the
        # structured log so the audit trail is preserved.
        if len(plaintext_justification.strip()) < _CORS_JUSTIFICATION_MIN_CHARS:
            raise CorsOriginPolicyError(
                "CORS_ORIGINS_ALLOW_PLAINTEXT_LAN=true requires a "
                "CORS_PLAINTEXT_JUSTIFICATION of at least "
                f"{_CORS_JUSTIFICATION_MIN_CHARS} characters explaining why the "
                "production CORS policy is being bypassed. This justification "
                "is written to the startup log as an audit record. "
                "Example: 'TEMPORARY: staging brought up on private LB "
                "2026-04-20 for load test — rollback ticket FX-1234'."
            )
        return

    for origin in origins:
        classification = _classify_cors_origin(origin)
        if classification == "ok":
            continue
        raise CorsOriginPolicyError(
            f"CORS origin {origin!r} violates production policy "
            f"(reason: {classification}). Production allows only origins "
            "with scheme=https AND a non-private / non-loopback host. "
            "Update CORS_ALLOWED_ORIGINS to an HTTPS public origin "
            "(e.g. 'https://app.fxlab.example.com'), or — only if "
            "legitimately required and auditable — set "
            "CORS_ORIGINS_ALLOW_PLAINTEXT_LAN=true paired with a "
            "CORS_PLAINTEXT_JUSTIFICATION."
        )


# ---------------------------------------------------------------------------
# libpq sslmode policy (C1 — 2026-04-15 remediation)
# ---------------------------------------------------------------------------
#
# These tuples are module-level constants rather than function locals so
# they can be imported by tests and by any future command-line helper
# (e.g. a "validate deployment manifest" tool) without re-declaring the
# security contract in two places.

#: libpq sslmode values that guarantee an encrypted channel. Accepted
#: in every environment, including production.
_STRICT_POSTGRES_SSLMODES: frozenset[str] = frozenset({"require", "verify-ca", "verify-full"})

#: libpq sslmode values that do NOT guarantee an encrypted channel.
#: Rejected when ``ENVIRONMENT=production``. Allowed in development,
#: staging, and test so local workflows remain frictionless against a
#: docker-compose Postgres on a private network.
_WEAK_POSTGRES_SSLMODES: frozenset[str] = frozenset({"disable", "allow", "prefer"})


def _extract_sslmode(database_url: str) -> str | None:
    """
    Extract the sslmode value from a PostgreSQL DSN.

    Handles both DSN styles libpq accepts:

        postgresql://user:pass@host:5432/db?sslmode=require
        postgresql://user:pass@host:5432/db?sslmode=require&application_name=fxlab

    Args:
        database_url: The full DATABASE_URL string. Callers should
            pre-filter to URLs that begin with ``postgresql``;
            non-postgres URLs return None here too but it is cleaner
            not to invoke the function on them.

    Returns:
        The raw sslmode value (lower-cased) if present in the query
        string, or ``None`` if the URL has no sslmode parameter. The
        returned value is *not* validated against libpq's known set —
        validation is the caller's job and happens in
        ``_enforce_postgres_sslmode``.

    Example:
        >>> _extract_sslmode("postgresql://u:p@h/db?sslmode=require")
        'require'
        >>> _extract_sslmode("postgresql://u:p@h/db") is None
        True
    """
    # Splitting on '?' is sufficient because libpq does not accept
    # fragment identifiers in DSNs. We then split on '&' for multiple
    # parameters.
    if "?" not in database_url:
        return None
    query = database_url.split("?", 1)[1]
    for pair in query.split("&"):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        if key.lower() == "sslmode":
            return value.strip().lower()
    return None


def _enforce_postgres_sslmode(database_url: str, environment: str) -> None:
    """
    Enforce the production sslmode policy on a PostgreSQL DATABASE_URL.

    Behaviour matrix:

        environment == "production"
            sslmode missing  → RuntimeError (must be explicit)
            sslmode weak     → RuntimeError (disable/allow/prefer)
            sslmode strict   → pass (require/verify-ca/verify-full)
            sslmode unknown  → RuntimeError (fail closed)

        environment != "production"
            any value        → pass (local dev must remain frictionless)
            missing          → WARNING log (advisory only)

    Args:
        database_url: A DATABASE_URL that has already been confirmed to
            begin with ``postgresql``. Behaviour is undefined for
            non-postgres URLs.
        environment: The current ``ENVIRONMENT`` value. Only the
            literal string ``"production"`` triggers enforcement.

    Raises:
        RuntimeError: In production, when sslmode is missing, weak, or
            unrecognised. The message names the offending value and
            enumerates the allowed values so the operator can fix the
            manifest in one edit.

    Example:
        >>> _enforce_postgres_sslmode(
        ...     "postgresql://u:p@h/db?sslmode=require", "production"
        ... )
        # returns None, no exception
        >>> _enforce_postgres_sslmode(
        ...     "postgresql://u:p@h/db?sslmode=prefer", "production"
        ... )
        Traceback (most recent call last):
            ...
        RuntimeError: DATABASE_URL sslmode=prefer ...
    """
    sslmode = _extract_sslmode(database_url)
    strict_list = ", ".join(sorted(_STRICT_POSTGRES_SSLMODES))

    if environment != "production":
        # Outside production, sslmode is advisory. A missing value still
        # earns a WARNING because pre-prod parity matters, but it is
        # not fatal.
        if sslmode is None:
            logger.warning(
                "startup.db_ssl_not_configured",
                warning=(
                    "DATABASE_URL does not include sslmode parameter. "
                    f"Production deployments will require one of: {strict_list}."
                ),
                component="startup",
            )
        return

    # --- Production enforcement below ---------------------------------------

    if sslmode is None:
        raise RuntimeError(
            "DATABASE_URL does not include sslmode parameter. "
            "Production PostgreSQL connections MUST use one of: "
            f"{strict_list}. "
            "Without SSL, credentials and trading data travel in plaintext. "
            "Add ?sslmode=require to your DATABASE_URL."
        )

    if sslmode in _WEAK_POSTGRES_SSLMODES:
        raise RuntimeError(
            f"DATABASE_URL sslmode={sslmode} is not permitted in production. "
            f"libpq '{sslmode}' does not guarantee an encrypted connection "
            "(it either disables SSL, tries it opportunistically, or "
            "silently falls back to plaintext on negotiation failure). "
            f"Production deployments MUST use one of: {strict_list}. "
            "Update the DATABASE_URL in your secret manifest and redeploy."
        )

    if sslmode not in _STRICT_POSTGRES_SSLMODES:
        # Unknown value — fail closed rather than assume it is safe.
        # libpq itself would reject this at connect time, but we would
        # prefer to fail at startup with a named error than produce a
        # ConnectionRefused 30 s later.
        raise RuntimeError(
            f"DATABASE_URL sslmode={sslmode} is not a recognised libpq value. "
            f"Production deployments MUST use one of: {strict_list}. "
            "Check the DATABASE_URL in your secret manifest for typos."
        )

    # sslmode is in _STRICT_POSTGRES_SSLMODES — pass.


def _validate_startup_secrets() -> None:
    """
    Validate that all required secrets are configured at startup.

    Performs eager validation so misconfiguration is caught immediately
    rather than surfacing as a 500/502 on the first request.  In test
    environments, most checks are skipped (mocks provide secrets), but the
    production sentinel guard always runs.

    Raises:
        RuntimeError: If a required secret is missing or invalid in
            non-test environments, OR if ENVIRONMENT=test is set in a
            production build (sentinel file exists).
    """
    env = os.environ.get("ENVIRONMENT", "")

    # --- Production sentinel guard (AUTH-2) -----------------------------------
    # Block ENVIRONMENT=test in production Docker images to prevent accidental
    # TEST_TOKEN bypass and deterministic secret fallback.
    if env == "test":
        if os.path.exists(_PRODUCTION_SENTINEL):
            raise RuntimeError(
                "CRITICAL: ENVIRONMENT=test is not permitted in production builds. "
                "This Docker image was built for production use. The TEST_TOKEN "
                "bypass and deterministic JWT secret are disabled in production. "
                "Remove ENVIRONMENT=test from your environment configuration."
            )
        logger.warning(
            "startup.test_mode_active",
            warning="TEST_TOKEN bypass and deterministic JWT secret are active. "
            "This is NOT safe for production use.",
            component="startup",
        )
        return  # Tests inject their own secrets via mocks

    # --- SSL mode enforcement for PostgreSQL (INFRA-2 / H1.7 / C1) -----------
    #
    # libpq defines six sslmode values. Three guarantee encryption
    # ("require", "verify-ca", "verify-full") and are accepted in
    # production. The other three are rejected in production:
    #
    #   - disable : no SSL at all — credentials travel in plaintext.
    #   - allow   : SSL only if the server initiates — effectively disable
    #               against a misconfigured server.
    #   - prefer  : tries SSL but silently falls back to plaintext on
    #               negotiation failure — indistinguishable from disable
    #               when it matters most.
    #
    # The legacy H1.7 check only rejected DATABASE_URL strings that
    # lacked sslmode entirely; an explicit-but-weak value slipped
    # through. That gap was exercised in the 2026-04-15 minitux failure
    # (DATABASE_URL contained "?sslmode=prefer"). C1 closes it.
    #
    # Non-production environments accept all six values so local dev
    # (docker-compose, minitux) and integration tests are frictionless.
    # Minitux is designated development per the environment policy.
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgresql"):
        _enforce_postgres_sslmode(database_url, env)

    from services.api.infrastructure.secret_provider_factory import get_provider

    provider = get_provider()

    # -- JWT_SECRET_KEY: must be present and >= 32 bytes -----------------------
    try:
        jwt_key = provider.get_secret("JWT_SECRET_KEY")
        if len(jwt_key.encode("utf-8")) < 32:
            raise RuntimeError(
                f"JWT_SECRET_KEY must be at least 32 bytes for HS256 security. "
                f"Current length: {len(jwt_key.encode('utf-8'))} bytes. "
                'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        logger.info(
            "startup.secret_validated",
            key="JWT_SECRET_KEY",
            key_length=len(jwt_key.encode("utf-8")),
            component="startup",
        )
    except KeyError as exc:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. This is required in non-test environments. "
            'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
        ) from exc

    # -- DATABASE_URL: must be present -----------------------------------------
    try:
        db_url = provider.get_secret("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is empty.")
        logger.info(
            "startup.secret_validated",
            key="DATABASE_URL",
            # Log URL prefix only — never log credentials
            url_prefix=db_url.split("://")[0] + "://..." if "://" in db_url else "unknown",
            component="startup",
        )
    except KeyError:
        logger.warning(
            "startup.secret_missing",
            key="DATABASE_URL",
            detail="Not set — falling back to SQLite",
            component="startup",
        )

    # -- KEYCLOAK_ADMIN_CLIENT_SECRET: required only when Keycloak is enabled --
    keycloak_url = os.environ.get("KEYCLOAK_URL", "")
    if keycloak_url:
        try:
            provider.get_secret("KEYCLOAK_ADMIN_CLIENT_SECRET")
            logger.info(
                "startup.secret_validated",
                key="KEYCLOAK_ADMIN_CLIENT_SECRET",
                component="startup",
            )
        except KeyError as exc:
            raise RuntimeError(
                "KEYCLOAK_ADMIN_CLIENT_SECRET is required when KEYCLOAK_URL is set. "
                "Retrieve it from the Keycloak admin console under the fxlab-api client."
            ) from exc


# Module-level drain middleware instance — shared between lifespan and
# middleware stack so the shutdown sequence can signal the middleware to
# reject new requests while in-flight ones complete.
_drain_middleware = DrainMiddleware()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager with graceful shutdown (M11).

    Startup sequence:
    1. Check pydantic-core compiled extension availability.
    2. Validate startup secrets (JWT, DB, Keycloak).
    3. Verify Redis health (in production with redis rate limiter).
    4. Auto-create SQLite tables for dev/test (Alembic handles production).
    5. Initialize artifact storage backend (MinIO or local filesystem).
    6. Run startup reconciliation for registered broker adapters (if any).
    7. Log startup event.

    Shutdown sequence (via GracefulLifecycleManager):
    1. Stop accepting new requests (drain middleware → 503).
    2. Wait for in-flight requests to drain (configurable timeout).
    3. Reconcile each active deployment against broker state.
    4. Deregister all broker adapters (disconnect from brokers).
    5. Dispose database connection pool.
    6. Log shutdown summary with timing and counts.

    On shutdown, disposes all pooled database connections to ensure
    a clean closure of the connection pool. SQLite in-memory databases
    are NOT disposed to preserve test data across TestClient instances.
    """
    from services.api.db import Base, engine
    from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
    from services.api.infrastructure.lifecycle_manager import GracefulLifecycleManager
    from services.api.infrastructure.redis_health import verify_redis_connection

    # D1 — Outer ConfigError trap. Any ConfigError that propagates out of a
    # startup phase below is caught here, reported as a single
    # startup.aborted structured event, and converted to sys.exit(3). The
    # distinctive exit code tells the orchestrator (docker compose
    # restart: on-failure) that this was a permanent configuration error —
    # the restart budget still counts it, so after the configured max
    # attempts the service gives up instead of spinning workers forever on
    # the same defect. Shutdown code below the `yield` is intentionally
    # outside this try: shutdown runs only when startup succeeded.
    try:
        # Emit versions first — this is the single most useful log line when
        # triaging "it works on my laptop but fails on minitux" style issues.
        _log_runtime_versions()

        with _startup_phase("pydantic_core_check"):
            _check_pydantic_core()
        with _startup_phase("validate_startup_secrets"):
            _validate_startup_secrets()

        # C2 enforcement (2026-04-15 v2 remediation): validate the CORS
        # allowlist against the production policy. In production,
        # plaintext-scheme and private-IP / loopback origins raise
        # CorsOriginPolicyError (a ConfigError subclass) unless the
        # audited escape hatch is engaged. In non-production, validation
        # is a no-op so local dev against localhost / LAN keeps working.
        #
        # This MUST run inside lifespan (not at module scope) so that
        # the outer ConfigError catch clause produces a deterministic
        # exit(3) on policy violations, instead of an unhandled
        # import-time crash that causes uvicorn to respawn-loop forever.
        with _startup_phase("cors_origin_policy"):
            _validate_cors_origins(
                origins=_cors_origins,
                environment=os.environ.get("ENVIRONMENT", ""),
                allow_plaintext_lan=_cors_allow_plaintext_lan,
                plaintext_justification=_cors_plaintext_justification,
            )
            if os.environ.get("ENVIRONMENT", "") == "production" and _cors_allow_plaintext_lan:
                logger.warning(
                    "cors.plaintext_lan_bypass_active",
                    justification=_cors_plaintext_justification,
                    origins=_cors_origins,
                    component="startup",
                    warning=(
                        "CORS_ORIGINS_ALLOW_PLAINTEXT_LAN=true is active in "
                        "production. Production CORS policy is bypassed. "
                        "Audit justification recorded."
                    ),
                )

        # Verify Redis health in production if rate limiting is Redis-backed.
        # This ensures the application fails fast if critical infrastructure
        # is unavailable, rather than degrading silently to in-memory fallback.
        environment = os.environ.get("ENVIRONMENT", "").lower()
        rate_limit_backend = os.environ.get("RATE_LIMIT_BACKEND", "memory").lower()

        if environment == "production" and rate_limit_backend == "redis":
            redis_url = os.environ.get("REDIS_URL", "")
            if not redis_url:
                raise RuntimeError(
                    "REDIS_URL is required in production when RATE_LIMIT_BACKEND=redis. "
                    "Set REDIS_URL to your Redis cluster endpoint "
                    "(e.g. redis://redis:6379/0)."
                )
            # Phase-wrap so the operator log carries an explicit
            # startup.phase_failed event for this phase when Redis is
            # misconfigured. Without this wrap the failure surfaces as a
            # bare traceback — which is what broke minitux triage on
            # 2026-04-15.
            try:
                with _startup_phase(
                    "redis_health_check",
                    environment="production",
                    backend="redis",
                    redis_url_scheme=redis_url.split("://", 1)[0] + "://..."
                    if "://" in redis_url
                    else "unset",
                ):
                    verify_redis_connection(redis_url, timeout_seconds=5.0)
                logger.info(
                    "redis.health_check_passed",
                    component="startup",
                )
            except Exception as exc:
                logger.critical(
                    "redis.health_check_failed",
                    error=str(exc),
                    component="startup",
                    detail="Redis is required in production for rate limiting. "
                    "Startup is blocked. Ensure Redis is available and configured.",
                )
                raise
        elif rate_limit_backend == "redis":
            # Non-production: log warning if Redis health check fails, but allow startup
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            try:
                with _startup_phase(
                    "redis_health_check",
                    environment=environment or "unset",
                    backend="redis",
                    fallback_on_failure="in_memory_rate_limiter",
                    redis_url_scheme=redis_url.split("://", 1)[0] + "://..."
                    if "://" in redis_url
                    else "unset",
                ):
                    verify_redis_connection(redis_url, timeout_seconds=5.0)
                logger.info(
                    "redis.health_check_passed",
                    component="startup",
                )
            except Exception as exc:
                logger.warning(
                    "redis.health_check_failed",
                    error=str(exc),
                    component="startup",
                    detail="Redis is unavailable. Rate limiting will fall back to in-memory. "
                    "This is acceptable for development but not for production.",
                )

        # Auto-create tables when backed by SQLite (dev / test).
        # Production uses Alembic migrations against PostgreSQL.
        db_url = str(engine.url)
        if db_url.startswith("sqlite"):
            Base.metadata.create_all(engine)
            logger.info(
                "db.tables_created",
                component="startup",
                detail="SQLite backend — auto-created tables from ORM metadata.",
            )

        # Initialize artifact storage backend (MinIO or local filesystem).
        # In production with ARTIFACT_STORAGE_BACKEND=minio, this creates the
        # required S3 buckets.  In dev/test with local backend, this creates the
        # root directory.  Failures here are non-fatal: the application starts
        # but artifact upload/download routes will return 503 until storage is
        # available.  This is intentional — the API should serve non-artifact
        # requests even when the storage backend is temporarily unreachable.
        #
        # Phase-wrapped so a MinIO misconfiguration surfaces as a structured
        # startup.phase_failed event (with duration_ms and exc_info) before
        # the degrade-to-None fallback kicks in. Without this wrap operators
        # had to correlate "artifact_storage.initialization_failed" with
        # whatever traceback happened to hit stderr to figure out which
        # backend and which credential path were in play.
        try:
            with _startup_phase(
                "artifact_storage_init",
                backend=os.environ.get("ARTIFACT_STORAGE_BACKEND", "local"),
            ):
                from services.api.routes.artifacts import get_artifact_storage

                artifact_storage = get_artifact_storage()
                artifact_storage.initialize(correlation_id="startup")
                app.state.artifact_storage = artifact_storage
            logger.info(
                "artifact_storage.initialized",
                backend=os.environ.get("ARTIFACT_STORAGE_BACKEND", "local"),
                component="startup",
            )
        except Exception as exc:
            logger.warning(
                "artifact_storage.initialization_failed",
                error=str(exc),
                backend=os.environ.get("ARTIFACT_STORAGE_BACKEND", "local"),
                component="startup",
                detail="Artifact storage unavailable — upload/download routes may fail.",
            )
            app.state.artifact_storage = None

        # Build the lifecycle manager for coordinated shutdown.
        # The broker registry is instantiated here — in production, adapters
        # are registered by the deployment service during normal operation.
        # The drain timeout is configurable via DRAIN_TIMEOUT_S env var.
        broker_registry = BrokerAdapterRegistry()
        drain_timeout_s = float(os.environ.get("DRAIN_TIMEOUT_S", "30"))

        lifecycle_manager = GracefulLifecycleManager(
            drain=_drain_middleware,
            broker_registry=broker_registry,
            engine=engine,
            drain_timeout_s=drain_timeout_s,
        )

        # Store references on app.state so route handlers and tests
        # can access the registry and lifecycle manager if needed.
        app.state.broker_registry = broker_registry
        app.state.lifecycle_manager = lifecycle_manager
        app.state.drain = _drain_middleware

        # Run startup reconciliation for any pre-registered adapters.
        lifecycle_manager.startup_reconciliation()

        # Run orphaned order recovery for all active live deployments.
        # This detects orders that were submitted to brokers but not recorded
        # internally due to crashes after submission but before acknowledgment.
        #
        # Phase-wrapped so operator logs carry an explicit
        # startup.phase_failed event when recovery fails at startup. The
        # except clause below still emits orphan_recovery.startup_failed for
        # context-specific messaging.
        try:
            with _startup_phase("orphan_recovery"):
                from services.api.db import SessionLocal
                from services.api.services.orphaned_order_recovery_service import (
                    OrphanedOrderRecoveryService,
                )

                # Instantiate repositories for orphan recovery
                db_session = SessionLocal()
                try:
                    from services.api.repositories.sql_deployment_repository import (
                        SqlDeploymentRepository,
                    )
                    from services.api.repositories.sql_execution_event_repository import (
                        SqlExecutionEventRepository,
                    )
                    from services.api.repositories.sql_order_repository import (
                        SqlOrderRepository,
                    )

                    deployment_repo = SqlDeploymentRepository(db_session)
                    order_repo = SqlOrderRepository(db_session)
                    event_repo = SqlExecutionEventRepository(db_session)

                    recovery_service = OrphanedOrderRecoveryService(
                        deployment_repo=deployment_repo,
                        order_repo=order_repo,
                        execution_event_repo=event_repo,
                        broker_registry=broker_registry,
                    )

                    # Run recovery for all active live deployments
                    reports = recovery_service.recover_all_deployments(
                        correlation_id="startup-orphan-recovery"
                    )

                    logger.info(
                        "orphan_recovery.startup_completed",
                        deployments_recovered=len(reports),
                        total_recovered=sum(r.recovered_count for r in reports),
                        total_failed=sum(r.failed_count for r in reports),
                        component="startup",
                    )
                finally:
                    db_session.close()
        except Exception as exc:
            logger.warning(
                "orphan_recovery.startup_failed",
                error=str(exc),
                component="startup",
                exc_info=True,
                detail="Orphaned order recovery failed at startup. Continuing without recovery.",
            )

        # Wire the LiveExecutionService for live trading endpoints.
        # This instantiates all dependencies and registers the service with the
        # live routes module so that /live/* endpoints have access to it.
        #
        # Phase-wrapped via _startup_phase so phase_begin / phase_complete /
        # phase_failed events are emitted consistently with every other
        # startup phase. On failure the except clause below preserves the
        # long-standing "do not abort startup, degrade to 503 on /live/*"
        # policy — but _startup_phase has already logged the structured
        # phase_failed event with exc_info, so the live_execution.wiring_failed
        # message is purely contextual.
        try:
            with _startup_phase("live_execution_wiring"):
                from services.api.db import SessionLocal
                from services.api.repositories.sql_deployment_repository import (
                    SqlDeploymentRepository,
                )
                from services.api.repositories.sql_execution_event_repository import (
                    SqlExecutionEventRepository,
                )
                from services.api.repositories.sql_kill_switch_event_repository import (
                    SqlKillSwitchEventRepository,
                )
                from services.api.repositories.sql_order_repository import SqlOrderRepository
                from services.api.repositories.sql_position_repository import (
                    SqlPositionRepository,
                )
                from services.api.repositories.sql_risk_event_repository import (
                    SqlRiskEventRepository,
                )
                from services.api.routes.live import set_live_execution_service
                from services.api.services.kill_switch_service import KillSwitchService
                from services.api.services.live_execution_service import LiveExecutionService
                from services.api.services.risk_gate_service import RiskGateService

                # Create a fresh session for LiveExecutionService wiring.
                # This session is held for the lifetime of the app and used by the
                # service for all order and position persistence.
                db_session_live = SessionLocal()

                # Instantiate repositories for live execution
                deployment_repo = SqlDeploymentRepository(db=db_session_live)
                order_repo = SqlOrderRepository(db=db_session_live)
                position_repo = SqlPositionRepository(db=db_session_live)
                execution_event_repo = SqlExecutionEventRepository(db=db_session_live)
                risk_event_repo = SqlRiskEventRepository(db=db_session_live)
                ks_event_repo = SqlKillSwitchEventRepository(db=db_session_live)

                # Instantiate RiskGateService for pre-trade enforcement
                risk_gate = RiskGateService(
                    deployment_repo=deployment_repo,
                    risk_event_repo=risk_event_repo,
                )

                # Instantiate KillSwitchService for halt enforcement
                # Build a dict mapping deployment_id → BrokerAdapterInterface for the service.
                # This is extracted from the broker registry's internal _registry dict.
                adapter_registry_dict: dict[str, Any] = {}
                with broker_registry._lock:
                    for deployment_id, (adapter, _broker_type) in broker_registry._registry.items():
                        adapter_registry_dict[deployment_id] = adapter

                kill_switch_service = KillSwitchService(
                    deployment_repo=deployment_repo,
                    ks_event_repo=ks_event_repo,
                    adapter_registry=adapter_registry_dict,
                )

                # Instantiate LiveExecutionService with all dependencies.
                # The transaction_manager parameter is optional; when None, callers
                # are responsible for transaction management at the request level.
                live_execution_service = LiveExecutionService(
                    deployment_repo=deployment_repo,
                    order_repo=order_repo,
                    position_repo=position_repo,
                    execution_event_repo=execution_event_repo,
                    risk_gate=risk_gate,
                    broker_registry=broker_registry,
                    kill_switch_service=kill_switch_service,
                    transaction_manager=None,  # Optional: can be wired if explicit tx boundary is needed
                )

                # Register the service with the live routes module so endpoints can access it
                set_live_execution_service(live_execution_service)

                # Store session and service references on app.state for graceful shutdown
                # if needed in the future
                app.state.live_execution_db_session = db_session_live
                app.state.live_execution_service = live_execution_service

                logger.info(
                    "live_execution.service_initialized",
                    component="startup",
                    detail="LiveExecutionService wired with all dependencies and registered with /live routes.",
                )
        except Exception as exc:
            # _startup_phase already logged startup.phase_failed with exc_info
            # and duration_ms. This critical log carries the degradation policy
            # context so operators know the API is continuing without live
            # trading rather than failing startup.
            logger.critical(
                "live_execution.wiring_failed",
                error=str(exc),
                component="startup",
                detail="Failed to wire LiveExecutionService at startup. "
                "Live trading endpoints will return 503 Service Unavailable.",
            )
            # Do not re-raise — allow the API to start without live execution.
            # This permits other endpoints to function while live trading is unavailable.

        # ---------------------------------------------------------------------
        # Periodic broker-vs-internal reconciliation (M19 production hardening)
        # ---------------------------------------------------------------------
        # Startup-only reconciliation closes the crash-recovery window but a
        # mid-day divergence between internal order/position state and broker
        # state is only caught at the next restart. A periodic reconciliation
        # bounds that divergence window to the configured interval.
        #
        # Wiring notes:
        # - This block is INTENTIONALLY self-contained. It does NOT reference
        #   any local variables from the LiveExecutionService wiring block
        #   above (adapter_registry_dict, db_session_live, etc.) — if that
        #   block raises, those names never get bound and any reference here
        #   would NameError inside this try/except, producing a misleading
        #   "periodic_reconciliation.wiring_failed" log whose real root cause
        #   is in the LiveExecutionService block. Each wiring block builds
        #   what it needs from the durable inputs (broker_registry + SessionLocal).
        # - Each tick is given its own fresh SQLAlchemy Session via a factory,
        #   because a single Session is NOT safe to share across threads
        #   (SQLAlchemy docs). The factory constructs a session + repos +
        #   ReconciliationService per tick.
        # - The broker adapter registry is shared; adapter registration is
        #   already guarded by BrokerAdapterRegistry's internal lock.
        # - RECONCILIATION_INTERVAL_SECONDS controls the cadence (default 300s
        #   = 5 min). Set to 0 to disable the periodic job entirely.
        app.state.periodic_reconciliation_job = None
        try:
            with _startup_phase(
                "periodic_reconciliation_wiring",
                interval_s_env=os.environ.get("RECONCILIATION_INTERVAL_SECONDS", "300"),
            ):
                from services.api.db import SessionLocal
                from services.api.infrastructure.periodic_reconciliation_job import (
                    PeriodicReconciliationJob,
                )
                from services.api.repositories.sql_deployment_repository import (
                    SqlDeploymentRepository,
                )
                from services.api.repositories.sql_order_repository import (
                    SqlOrderRepository,
                )
                from services.api.repositories.sql_position_repository import (
                    SqlPositionRepository,
                )
                from services.api.repositories.sql_reconciliation_repository import (
                    SqlReconciliationRepository,
                )
                from services.api.routes.reconciliation import (
                    set_reconciliation_service,
                )
                from services.api.services.reconciliation_service import (
                    ReconciliationService,
                )

                # Per-tick factory: fresh session, fresh repos, fresh adapter
                # snapshot, fresh service. A fresh Session per tick is required
                # because SQLAlchemy Session instances are NOT thread-safe.
                def _build_periodic_reconciliation_service() -> ReconciliationService:
                    """
                    Build a ReconciliationService wired with a fresh session.

                    The session is intentionally leaked to the GC (no explicit
                    close in the factory) because SessionLocal()'s default
                    sessionmaker returns regular Session objects — these are
                    cheap to let fall out of scope. Production should move to
                    a context-managed factory once scoped_session is introduced.
                    """
                    tick_session = SessionLocal()
                    dep_repo = SqlDeploymentRepository(db=tick_session)
                    order_repo_tick = SqlOrderRepository(db=tick_session)
                    position_repo_tick = SqlPositionRepository(db=tick_session)
                    recon_repo = SqlReconciliationRepository(db=tick_session)

                    # Build a per-tick adapter map from the shared broker
                    # registry. The registry's internal lock makes this copy
                    # safe. We rebuild on every tick so adapters registered
                    # after startup are picked up automatically.
                    tick_adapter_map: dict[str, Any] = {}
                    with broker_registry._lock:
                        for dep_id, (adapter, _btype) in broker_registry._registry.items():
                            tick_adapter_map[dep_id] = adapter

                    return ReconciliationService(
                        deployment_repo=dep_repo,
                        reconciliation_repo=recon_repo,
                        adapter_registry=tick_adapter_map,
                        order_repo=order_repo_tick,
                        position_repo=position_repo_tick,
                    )

                # Separate session + repo for listing active deployments in
                # the job's check_and_reconcile() — list_by_state is a
                # single-shot read, safe to hold for the job's lifetime.
                recon_list_session = SessionLocal()
                app.state.periodic_reconciliation_session = recon_list_session
                recon_deployment_repo = SqlDeploymentRepository(db=recon_list_session)

                # Also register a service with the /reconciliation routes so
                # on-demand endpoints work. Build a SEPARATE long-lived
                # session + adapter snapshot here rather than reusing anything
                # from the LiveExecutionService block, so a failure there does
                # not cascade to disable on-demand reconciliation here.
                routes_session = SessionLocal()
                app.state.periodic_reconciliation_routes_session = routes_session
                routes_adapter_map: dict[str, Any] = {}
                with broker_registry._lock:
                    for dep_id, (adapter, _btype) in broker_registry._registry.items():
                        routes_adapter_map[dep_id] = adapter
                set_reconciliation_service(
                    ReconciliationService(
                        deployment_repo=SqlDeploymentRepository(db=routes_session),
                        reconciliation_repo=SqlReconciliationRepository(db=routes_session),
                        adapter_registry=routes_adapter_map,
                        order_repo=SqlOrderRepository(db=routes_session),
                        position_repo=SqlPositionRepository(db=routes_session),
                    )
                )

                interval_s = float(os.environ.get("RECONCILIATION_INTERVAL_SECONDS", "300"))
                periodic_job = PeriodicReconciliationJob(
                    reconciliation_service_factory=_build_periodic_reconciliation_service,
                    deployment_repo=recon_deployment_repo,
                    check_interval_seconds=interval_s,
                )
                periodic_job.start()
                app.state.periodic_reconciliation_job = periodic_job
                logger.info(
                    "periodic_reconciliation.wired",
                    component="startup",
                    check_interval_seconds=interval_s,
                    enabled=interval_s > 0,
                )
        except Exception:
            # _startup_phase already logged startup.phase_failed with exc_info.
            # This warning is the domain-specific follow-up explaining the
            # operational impact so oncall knows the divergence-detection
            # window has regressed to "next restart only".
            logger.warning(
                "periodic_reconciliation.wiring_failed",
                component="startup",
                detail=(
                    "Periodic reconciliation job did not start. Startup "
                    "reconciliation still ran; divergences introduced "
                    "mid-process-life will only be caught at next restart "
                    "until the periodic job is repaired. See the preceding "
                    "startup.phase_failed log for the root-cause exception."
                ),
            )

        logger.info("api.startup", version="0.1.0")
    except ConfigError as exc:
        # Permanent configuration failure — do not let the orchestrator
        # spin forever on the same defect. The preceding
        # startup.phase_failed event already names the failed phase; this
        # aborted event is the single, obvious marker that the process
        # exited deterministically with code 3.
        logger.critical(
            "startup.aborted",
            component="startup",
            reason="config_error",
            error=str(exc),
            exit_code=3,
            exc_info=True,
            detail=(
                "API startup aborted due to a permanent configuration "
                "error. The process will exit with code 3. Operators: do "
                "not redeploy this configuration — retrying will hit the "
                "same defect. See the preceding startup.phase_failed event "
                "for the root-cause exception."
            ),
        )
        sys.exit(3)
    yield

    # Graceful shutdown: stop periodic job first so no new reconciliations
    # begin while the broker registry is torn down, then drain → reconcile
    # → deregister → dispose.
    periodic_job = getattr(app.state, "periodic_reconciliation_job", None)
    if periodic_job is not None:
        try:
            periodic_job.stop()
        except Exception:
            logger.warning(
                "periodic_reconciliation.stop_failed",
                component="shutdown",
                exc_info=True,
            )
    recon_list_session = getattr(app.state, "periodic_reconciliation_session", None)
    if recon_list_session is not None:
        try:
            recon_list_session.close()
        except Exception:
            logger.warning(
                "periodic_reconciliation.session_close_failed",
                component="shutdown",
                exc_info=True,
            )
    routes_session = getattr(app.state, "periodic_reconciliation_routes_session", None)
    if routes_session is not None:
        try:
            routes_session.close()
        except Exception:
            logger.warning(
                "periodic_reconciliation.routes_session_close_failed",
                component="shutdown",
                exc_info=True,
            )

    lifecycle_manager.shutdown()
    logger.info("api.shutdown", component="shutdown")


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FXLab Phase 3 API",
    description="Web UX and Governance API for FXLab trading platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

app.include_router(health.router)  # Health probe — unauthenticated, must be first
app.include_router(mobile_dashboard.router)  # BE-01: Mobile Dashboard Summary Endpoint
app.include_router(auth.router)  # M14-T8: OIDC auth (discovery, token, revoke, JWKS)
app.include_router(runs.router)
app.include_router(readiness.router)
app.include_router(exports.router)  # M13-T4: Export stubs (zip bundles in M31)
app.include_router(research.router)  # M13-T4: Research stubs (M25/M26 will implement)
app.include_router(
    governance.router, prefix="/governance", tags=["governance"]
)  # M13-T4: Governance misc
app.include_router(charts.router)  # M7: Chart + LTTB + Queue Backend APIs
app.include_router(data_certification.router)  # M8: Certification Viewer
app.include_router(parity.router)  # M8: Parity Dashboard
app.include_router(pnl.router)  # M9: P&L Attribution & Performance Tracking
app.include_router(promotions.router)
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
app.include_router(
    overrides.router, prefix="/overrides", tags=["overrides"]
)  # M23: Override request/get
app.include_router(
    strategies.router, prefix="/strategies", tags=["strategies"]
)  # M23: Draft autosave
app.include_router(
    audit_export.router, prefix="/audit", tags=["audit_export"]
)  # M12 (before audit explorer to avoid /{id} catch-all)
app.include_router(audit.router, prefix="/audit", tags=["audit"])
app.include_router(symbol_lineage.router, prefix="/symbols", tags=["symbol_lineage"])  # M9
app.include_router(observability.router)  # M11: Alerting + Observability Hardening
app.include_router(queues.router, prefix="/queues", tags=["queues"])
app.include_router(data_quality.router)  # Phase 8 M2: Data Quality API
app.include_router(execution_loop.router)  # Phase 8 M8: Execution Loop API
app.include_router(feed_health.router)
app.include_router(feeds.router)  # M6: Feed Registry + Versioned Config
app.include_router(artifacts.router)  # M5: Artifact Registry + Storage Abstraction
app.include_router(admin.router)  # M14-T8b: Admin panel (secrets + Keycloak user mgmt)
app.include_router(
    deployments.router, prefix="/deployments", tags=["deployments"]
)  # Phase 4 M2: Deployment State Machine
app.include_router(
    shadow.router, prefix="/shadow", tags=["shadow"]
)  # Phase 4 M3: Shadow Mode Pipeline
app.include_router(
    paper.router, prefix="/paper", tags=["paper"]
)  # Phase 4 M4: Paper Deployment Pipeline
app.include_router(live.router)  # Phase 6 M3: Live Execution Service
app.include_router(
    risk.router, prefix="/risk", tags=["risk"]
)  # Phase 4 M5: Risk Gate & Pre-Trade Checks
app.include_router(
    reconciliation.router, prefix="/reconciliation", tags=["reconciliation"]
)  # Phase 4 M6: Reconciliation Service
app.include_router(
    kill_switch.router, prefix="/kill-switch", tags=["kill-switch"]
)  # Phase 4 M7: Kill Switches & Emergency Posture
app.include_router(
    execution_analysis.router, prefix="/execution-analysis", tags=["execution-analysis"]
)  # Phase 4 M8: Execution Drift Analysis & Replay
app.include_router(
    compliance.router, prefix="/compliance", tags=["compliance"]
)  # Phase 4 M11: Trade Execution Reports for Regulatory Compliance
app.include_router(
    drills.router, prefix="/drills", tags=["drills"]
)  # Phase 4 M9: Runbooks, Drills & Production Hardening
app.include_router(
    ws_positions.router, tags=["websocket"]
)  # Phase 6 M7: Real-Time Position Dashboard (WebSocket)
app.include_router(market_data.router)  # Phase 7 M2: Market Data API Endpoints
app.include_router(indicators.router)  # Phase 7 M7: Indicator API Endpoints
app.include_router(risk_analytics.router)  # Phase 7 M8: Portfolio Risk Analytics
app.include_router(stress_test.router)  # Phase 7 M9: Stress Testing & Scenario Analysis
app.include_router(position_sizing.router)  # Phase 7 M10: Dynamic Position Sizing
app.include_router(risk_alert.router)  # Phase 7 M11: Risk Dashboard & Alerting
app.include_router(strategy_comparison.router)  # Phase 7 M13: Strategy Comparison & Ranking
app.include_router(ws_market_data.router)  # Phase 7 M3: Real-Time Market Data Streaming (WebSocket)
app.include_router(metrics_module.router)  # M14-T9: Prometheus metrics scrape endpoint

# ---------------------------------------------------------------------------
# CORS — read allowed origins from CORS_ALLOWED_ORIGINS env var.
# Defaults to localhost dev origins for local development.
#
# SECURITY NOTE: allow_origins=["*"] with allow_credentials=True is rejected
# by browsers (CORS spec §3.2.2 forbids wildcard + credentials). Production
# containers MUST set CORS_ALLOWED_ORIGINS to the actual frontend domain
# (e.g. "https://app.fxlab.example.com"). Multiple origins are
# comma-separated: "https://app.fxlab.example.com,https://beta.fxlab.example.com"
# ---------------------------------------------------------------------------
_cors_origins_raw: str = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173",
)
_cors_origins: list[str] = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

# -- C2 enforcement (2026-04-15 v2 remediation) ----------------------------
# CORS origin policy validation is performed inside the lifespan handler
# (see the ``cors_origin_policy`` startup phase), NOT at module scope.
#
# Prior to v2, _validate_cors_origins() was called here at module-import
# time. That was wrong for two reasons:
#   1. An import-time raise bypasses the lifespan ConfigError handler,
#      so uvicorn sees an unhandled exception and respawn-loops forever
#      instead of emitting exit(3).
#   2. The CorsOriginPolicyError class subclassed RuntimeError, not
#      ConfigError, so even if the raise had been inside lifespan,
#      the ``except ConfigError`` catch would not have caught it.
#
# The env-var reads and middleware registration below are safe at module
# scope — they never raise. Only the policy enforcement call moved.
_cors_allow_plaintext_lan: bool = (
    os.environ.get("CORS_ORIGINS_ALLOW_PLAINTEXT_LAN", "").lower() == "true"
)
_cors_plaintext_justification: str = os.environ.get("CORS_PLAINTEXT_JUSTIFICATION", "")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Correlation-ID",
        "X-Client-Source",
        "Idempotency-Key",
    ],
)

# ---------------------------------------------------------------------------
# M14-T1: Infrastructure hardening middleware stack
# Order (last-registered = outermost/runs first):
#   DrainMiddleware (runs first — rejects requests during shutdown)
#   CorrelationIDMiddleware (sets correlation context for all layers)
#   ClientSourceMiddleware (extracts X-Client-Source for audit tracking)
#   BodySizeLimitMiddleware (size check before rate limiting)
#   RateLimitMiddleware (rate limit enforcement)
#   IdempotencyMiddleware (dedup before business logic executes)
#   CORSMiddleware (already registered above)
# ---------------------------------------------------------------------------

app.add_middleware(IdempotencyMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(ClientSourceMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(type(_drain_middleware), drain_state=_drain_middleware)


# ---------------------------------------------------------------------------
# HTTPS enforcement — warn on plaintext requests in production
# ---------------------------------------------------------------------------

if os.environ.get("ENVIRONMENT") == "production":
    from starlette.middleware.base import BaseHTTPMiddleware as _BaseHttp

    class _HTTPSEnforcementMiddleware(_BaseHttp):
        """Log warnings when production requests arrive without TLS."""

        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            proto = request.headers.get("x-forwarded-proto", "http")
            if proto != "https":
                logger.warning(
                    "security.plaintext_request",
                    path=request.url.path,
                    x_forwarded_proto=proto,
                    client=request.client.host if request.client else "unknown",
                    component="https_enforcement",
                    detail="Production request received without HTTPS. "
                    "Ensure a TLS-terminating reverse proxy is in front of this service.",
                )
            return await call_next(request)

    app.add_middleware(_HTTPSEnforcementMiddleware)

# ---------------------------------------------------------------------------
# Global exception handlers — map domain & infrastructure exceptions to HTTP.
# Prevents 500s from leaking stack traces to clients.
# ---------------------------------------------------------------------------

from fastapi import Request as _Req  # noqa: E402 — exception handlers must follow app creation
from fastapi.responses import JSONResponse as _JsonResp  # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402

from libs.contracts.errors import NotFoundError, SeparationOfDutiesError  # noqa: E402
from libs.contracts.errors import ValidationError as DomainValidationError  # noqa: E402
from libs.contracts.rate_limit import RateLimitErrorResponse, RateLimitExceededError  # noqa: E402


@app.exception_handler(NotFoundError)
async def _handle_not_found(request: _Req, exc: NotFoundError) -> _JsonResp:
    return _JsonResp(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SeparationOfDutiesError)
async def _handle_sod(request: _Req, exc: SeparationOfDutiesError) -> _JsonResp:
    return _JsonResp(status_code=409, content={"detail": str(exc)})


@app.exception_handler(DomainValidationError)
async def _handle_validation(request: _Req, exc: DomainValidationError) -> _JsonResp:
    return _JsonResp(status_code=422, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def _handle_integrity(request: _Req, exc: IntegrityError) -> _JsonResp:
    logger.error(
        "db.integrity_error",
        error=str(exc.orig),
        component="exception_handler",
        exc_info=True,
    )
    return _JsonResp(
        status_code=409,
        content={"detail": "Data integrity conflict. The operation could not be completed."},
    )


@app.exception_handler(OperationalError)
async def _handle_operational(request: _Req, exc: OperationalError) -> _JsonResp:
    logger.error(
        "db.operational_error",
        error=str(exc.orig),
        component="exception_handler",
        exc_info=True,
    )
    return _JsonResp(
        status_code=503,
        content={"detail": "Service temporarily unavailable. Please retry."},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(RateLimitExceededError)
async def _handle_rate_limit(request: _Req, exc: RateLimitExceededError) -> _JsonResp:
    """
    Handle rate limit exceeded errors (429).

    Returns RateLimitErrorResponse with Retry-After header matching the
    calculated retry delay from the rate limiter.
    """
    response = RateLimitErrorResponse(
        detail=exc.detail,
        retry_after=exc.retry_after_seconds,
    )
    logger.warning(
        "rate_limit.exceeded_handled",
        scope=exc.scope,
        limit=exc.limit,
        window_seconds=exc.window_seconds,
        retry_after=exc.retry_after_seconds,
        component="exception_handler",
    )
    return _JsonResp(
        status_code=429,
        content=response.model_dump(),
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


logger.info("fastapi_app_initialized")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    """
    Root endpoint providing API metadata.

    Returns:
        API title and version.
    """
    return {"title": "FXLab Phase 3 Web UX API", "version": API_VERSION}


# ---------------------------------------------------------------------------
# Service-layer stubs — imported by route handlers and mocked in tests.
# ---------------------------------------------------------------------------


class _AuditServiceStub:
    """
    Stub audit service.

    Real implementation will be injected via dependency injection once the
    audit infrastructure is wired.  Tests mock this object directly via
    ``patch("services.api.main.audit_service")``.
    """

    def log_event(self, **kwargs: Any) -> None:  # noqa: D102
        logger.debug("audit.log_event.stub", **kwargs)


def check_permission(
    requester_id: str,
    permission: Any = None,
    rbac_service: Any = None,
) -> bool:
    """
    Check whether the requester has permission for the requested action.

    Args:
        requester_id: ULID of the user making the request.
        permission: Optional ``libs.authz.interfaces.rbac.Permission`` enum
                    value specifying the action to check.  When provided
                    together with ``rbac_service``, the decision is delegated
                    to the service.
        rbac_service: Optional ``RBACInterface`` implementation.  When
                      provided, the permission decision is delegated to it
                      rather than using the fallback stub.

    Returns:
        True if permission is granted; False otherwise.

    Note:
        Falls back to returning True (permissive stub) when no
        ``rbac_service`` is supplied, preserving backward compatibility
        with route handlers that call this without RBAC context.
        Tests that need to enforce RBAC can supply a ``MockRBACService``
        via the ``rbac_service`` parameter.
        Tests that need to suppress access entirely use
        ``patch("services.api.main.check_permission", return_value=False)``.
    """
    if rbac_service is not None and permission is not None:
        return rbac_service.has_permission(requester_id, permission)
    # Backward-compatible stub — returns True when no RBAC service is wired.
    return True


def get_run_results(run_id: str, db: Any = None) -> dict[str, Any] | None:
    """
    Retrieve results for a completed run.

    Queries the Run table by primary key and gathers associated artifacts
    and trial metrics. Returns None if the run does not exist.

    Args:
        run_id: ULID of the run.
        db: SQLAlchemy session. If None, creates a request-scoped session
            from SessionLocal (backward compat for tests that mock this).

    Returns:
        Dict with run_id, status, metrics (from trials), and artifacts list.
        None if the run is not found in the database.

    Example:
        results = get_run_results("01HABCDEF00000000000000000", db=session)
        # results["run_id"] == "01HABCDEF00000000000000000"
    """
    from libs.contracts.models import Artifact, Run, Trial
    from services.api.db import SessionLocal

    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        run = db.get(Run, run_id)
        if run is None:
            logger.debug(
                "get_run_results.not_found",
                run_id=run_id,
                component="main",
            )
            return None

        # Gather trial metrics
        trials = db.query(Trial).filter(Trial.run_id == run_id).all()
        trial_metrics = [
            {
                "trial_index": t.trial_index,
                "status": t.status,
                "metrics": t.metrics or {},
            }
            for t in trials
        ]

        # Gather artifacts
        artifacts = db.query(Artifact).filter(Artifact.run_id == run_id).all()
        artifact_list = [
            {
                "artifact_id": a.id,
                "artifact_type": a.artifact_type,
                "uri": a.uri,
                "size_bytes": a.size_bytes,
                "checksum": a.checksum,
            }
            for a in artifacts
        ]

        logger.info(
            "get_run_results.retrieved",
            run_id=run_id,
            trial_count=len(trial_metrics),
            artifact_count=len(artifact_list),
            component="main",
        )

        return {
            "run_id": run.id,
            "status": run.status,
            "run_type": run.run_type,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "metrics": trial_metrics,
            "artifacts": artifact_list,
        }
    finally:
        if close_session:
            db.close()


def get_readiness_report(run_id: str, db: Any = None) -> dict[str, Any] | None:
    """
    Retrieve the readiness report for a run.

    Queries the Run table and evaluates readiness based on run status,
    trial outcomes, and certification events. Returns None if the run
    does not exist.

    Args:
        run_id: ULID of the run.
        db: SQLAlchemy session. If None, creates a request-scoped session.

    Returns:
        Dict with run_id, readiness_grade, blockers list, and scoring evidence.
        None if the run is not found.

    Example:
        report = get_readiness_report("01HABCDEF00000000000000000", db=session)
        # report["readiness_grade"] in ("GREEN", "YELLOW", "RED", "UNKNOWN")
    """
    from libs.contracts.models import CertificationEvent, Run, Trial
    from services.api.db import SessionLocal

    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        run = db.get(Run, run_id)
        if run is None:
            logger.debug(
                "get_readiness_report.not_found",
                run_id=run_id,
                component="main",
            )
            return None

        blockers: list[str] = []
        evidence: dict[str, Any] = {}

        # Check run completion status
        if run.status != "completed":
            blockers.append(f"Run status is '{run.status}', expected 'completed'.")
            evidence["run_status"] = run.status

        # Check trial outcomes
        trials = db.query(Trial).filter(Trial.run_id == run_id).all()
        failed_trials = [t for t in trials if t.status == "failed"]
        evidence["total_trials"] = len(trials)
        evidence["failed_trials"] = len(failed_trials)

        if failed_trials:
            blockers.append(f"{len(failed_trials)} of {len(trials)} trials failed.")

        if len(trials) == 0:
            blockers.append("No trials found for this run.")

        # Check certification events
        certs = db.query(CertificationEvent).filter(CertificationEvent.run_id == run_id).all()
        evidence["certifications"] = len(certs)

        # Compute readiness grade
        if blockers:
            grade = "RED" if len(blockers) >= 2 else "YELLOW"
        elif len(certs) > 0:
            grade = "GREEN"
        else:
            grade = "YELLOW"  # No blockers but no certifications yet

        logger.info(
            "get_readiness_report.computed",
            run_id=run_id,
            grade=grade,
            blocker_count=len(blockers),
            component="main",
        )

        return {
            "run_id": run.id,
            "readiness_grade": grade,
            "blockers": blockers,
            "scoring_evidence": evidence,
        }
    finally:
        if close_session:
            db.close()


def submit_promotion_request(payload: Any, db: Any = None) -> dict[str, str]:
    """
    Create a promotion request record in the database.

    Persists a PromotionRequest with status='pending' and returns
    the generated ULID as the job_id.

    Args:
        payload: Validated PromotionRequest contract (or compatible object
                 with candidate_id, requester_id, target_environment, etc.).
        db: SQLAlchemy session. If None, creates a request-scoped session.

    Returns:
        Dict with ``job_id`` (ULID string) and ``status`` ("pending").

    Example:
        result = submit_promotion_request(payload, db=session)
        # result["job_id"] == "01H..."
        # result["status"] == "pending"
    """
    import ulid as _ulid_mod

    from libs.contracts.models import PromotionRequest
    from services.api.db import SessionLocal

    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        promo_id = str(_ulid_mod.ULID())

        # Extract fields from payload — supports both Pydantic models and dicts
        candidate_id = getattr(payload, "candidate_id", None) or (
            payload.get("candidate_id") if isinstance(payload, dict) else None
        )
        requester_id = getattr(payload, "requester_id", None) or (
            payload.get("requester_id") if isinstance(payload, dict) else None
        )
        target_env = getattr(payload, "target_environment", None) or (
            payload.get("target_environment") if isinstance(payload, dict) else None
        )
        if hasattr(target_env, "value"):
            target_env = target_env.value
        rationale = getattr(payload, "rationale", None) or (
            payload.get("rationale") if isinstance(payload, dict) else None
        )
        evidence_link = getattr(payload, "evidence_link", None) or (
            payload.get("evidence_link") if isinstance(payload, dict) else None
        )

        record = PromotionRequest(
            id=promo_id,
            candidate_id=candidate_id,
            requester_id=requester_id,
            target_environment=target_env or "paper",
            status="pending",
            rationale=rationale,
            evidence_link=evidence_link,
        )
        db.add(record)
        db.flush()

        logger.info(
            "submit_promotion_request.created",
            job_id=promo_id,
            candidate_id=candidate_id,
            component="main",
        )

        return {
            "job_id": promo_id,
            "status": "pending",
        }
    finally:
        if close_session:
            db.close()


# Singleton audit service stub — replaced in tests via patch.
audit_service = _AuditServiceStub()

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    "app",
    "audit_service",
    "check_permission",
    "get_readiness_report",
    "get_run_results",
    "submit_promotion_request",
]
