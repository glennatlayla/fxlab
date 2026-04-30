"""
scripts/validate_env.py
========================

FXLab credential / connectivity validator.

Reads `.env` (if present) plus the ambient process environment, then probes
every external dependency the platform needs at runtime:

- PostgreSQL    (DATABASE_URL or POSTGRES_* — opens a real connection)
- Redis         (REDIS_URL or REDIS_HOST/PORT — sends PING)
- MinIO/S3      (S3_ENDPOINT / MINIO_HOST / MINIO_PORT — health-ready probe)
- Keycloak      (KEYCLOAK_URL or VITE_OIDC_AUTHORITY — OIDC discovery, with
                 retry budget so a still-booting container doesn't FAIL early)
- JWT           (JWT_SECRET_KEY — confirms set + non-trivial length)
- Celery        (CELERY_BROKER_URL — confirms it parses; no broker connect)
- Azure KV      (AZURE_KEYVAULT_URL when SECRET_PROVIDER=azure — DNS resolve)
- OTel exporter (OTEL_EXPORTER_OTLP_ENDPOINT — host/port reachability)
- Exec modes    (ALLOWED_EXECUTION_MODES — warns loudly if "live" appears in
                 development environments)

Each probe prints PASS, WARN, SKIP, or FAIL.

Exit codes:
  0 — every configured service reachable (PASS or SKIP only, no FAIL/WARN)
  1 — at least one configured service FAILED
  2 — one or more services skipped because env vars unset (informational)
  3 — at least one probe returned WARN (configuration-suspicious but not
      a hard failure: live-execution mode in dev, OIDC retry budget
      exceeded but service is reachable, etc.)

Zero hard dependencies on FXLab internals — runs against a plain venv with
`psycopg2-binary`, `redis`, and `requests` installed (already in
requirements.txt).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# -------------------------- env loading --------------------------------------


def _load_dotenv(path: Path) -> None:
    """Best-effort .env loader — does not depend on python-dotenv."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Don't clobber an explicitly-set ambient variable.
        os.environ.setdefault(key, value)


# -------------------------- check primitives ---------------------------------


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS", "FAIL", "SKIP", "WARN"
    detail: str


def _pass(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "PASS", detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "FAIL", detail)


def _skip(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "SKIP", detail)


def _warn(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "WARN", detail)


# -------------------------- helpers ------------------------------------------


def _scrub_url(url: str) -> str:
    """Remove the password segment from a URL for safe printing."""
    parsed = urlparse(url)
    if parsed.password:
        netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
        return parsed._replace(netloc=netloc).geturl()
    return url


# -------------------------- individual checks --------------------------------


def check_postgres() -> CheckResult:
    name = "postgres"
    url = os.environ.get("DATABASE_URL")
    if not url:
        host = os.environ.get("POSTGRES_HOST")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB")
        user = os.environ.get("POSTGRES_USER")
        password = os.environ.get("POSTGRES_PASSWORD")
        if not all((host, db, user, password)):
            return _skip(name, "DATABASE_URL / POSTGRES_* not set")
        url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError:
        return _fail(name, "psycopg2 not installed")

    try:
        conn = psycopg2.connect(url, connect_timeout=5)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        conn.close()
        return _pass(name, _scrub_url(url))
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


def check_redis() -> CheckResult:
    name = "redis"
    url = os.environ.get("REDIS_URL")
    if not url:
        host = os.environ.get("REDIS_HOST")
        port = os.environ.get("REDIS_PORT", "6379")
        password = os.environ.get("REDIS_PASSWORD", "")
        if not host:
            return _skip(name, "REDIS_URL / REDIS_HOST not set")
        auth = f":{password}@" if password else ""
        url = f"redis://{auth}{host}:{port}/0"

    try:
        import redis  # type: ignore[import-not-found]
    except ImportError:
        return _fail(name, "redis not installed")

    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=5)
        if client.ping():
            return _pass(name, _scrub_url(url))
        return _fail(name, "PING returned falsy")
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


def check_minio() -> CheckResult:
    name = "minio/s3"
    endpoint = os.environ.get("S3_ENDPOINT")
    if not endpoint:
        host = os.environ.get("MINIO_HOST")
        port = os.environ.get("MINIO_PORT", "9000")
        if host:
            endpoint = f"http://{host}:{port}"
    if not endpoint:
        return _skip(name, "S3_ENDPOINT / MINIO_HOST not set")

    try:
        import requests
    except ImportError:
        return _fail(name, "requests not installed")

    try:
        resp = requests.get(endpoint.rstrip("/") + "/minio/health/ready", timeout=5)
        if resp.ok:
            return _pass(name, endpoint)
        return _fail(name, f"HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


def check_keycloak() -> CheckResult:
    name = "keycloak"
    authority = os.environ.get("KEYCLOAK_URL") or os.environ.get("VITE_OIDC_AUTHORITY")
    if not authority:
        return _skip(name, "KEYCLOAK_URL / VITE_OIDC_AUTHORITY not set")

    try:
        import requests
    except ImportError:
        return _fail(name, "requests not installed")

    realm = os.environ.get("KEYCLOAK_REALM", "fxlab")
    discovery = (
        authority.rstrip("/") + f"/realms/{realm}/.well-known/openid-configuration"
        if "/realms/" not in authority
        else authority.rstrip("/") + "/.well-known/openid-configuration"
    )

    # Retry budget — Keycloak's start-dev with realm import can take 60+s
    # on first boot. Retry every 3s for up to 30s before declaring failure.
    # On hosts where Keycloak hasn't been started, the first request fails
    # fast (connection refused) so the budget barely matters.
    import time

    budget_seconds = int(os.environ.get("KEYCLOAK_VALIDATE_BUDGET_SECONDS", "30"))
    deadline = time.monotonic() + budget_seconds
    last_err: str = ""
    while time.monotonic() < deadline:
        try:
            resp = requests.get(discovery, timeout=5)
            if resp.ok and "issuer" in resp.json():
                return _pass(name, discovery)
            last_err = f"HTTP {resp.status_code}"
            # 404 likely means realm not yet imported; transient on first boot.
            if resp.status_code != 404:
                return _fail(name, last_err)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(3)
    # Budget exhausted. Distinguish "service is reachable but realm 404"
    # (WARN — operator may not have imported realm yet) from "connection
    # refused" (FAIL — service isn't running).
    if last_err.startswith("HTTP 404"):
        return _warn(name, f"realm '{realm}' not found at {discovery} (after {budget_seconds}s)")
    return _fail(name, f"{last_err} (after {budget_seconds}s retry budget)")


def check_jwt_secret() -> CheckResult:
    name = "jwt-secret"
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        return _skip(name, "JWT_SECRET_KEY not set")
    if len(secret) < 32:
        return _fail(name, f"JWT_SECRET_KEY too short ({len(secret)} chars; ≥ 32 required)")
    return _pass(name, f"{len(secret)}-char secret present")


def check_celery_broker() -> CheckResult:
    name = "celery-broker"
    url = os.environ.get("CELERY_BROKER_URL")
    if not url:
        return _skip(name, "CELERY_BROKER_URL not set")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return _fail(name, f"unparseable URL: {url}")
    return _pass(name, _scrub_url(url))


def check_azure_keyvault() -> CheckResult:
    """When SECRET_PROVIDER=azure, AZURE_KEYVAULT_URL must DNS-resolve.

    Doesn't authenticate — that depends on managed identity / CLI / env-var
    chain that's environment-specific. A DNS resolve confirms the operator
    didn't typo the URL.
    """
    name = "azure-keyvault"
    if os.environ.get("SECRET_PROVIDER", "env") != "azure":
        return _skip(name, "SECRET_PROVIDER != azure")
    url = os.environ.get("AZURE_KEYVAULT_URL", "")
    if not url:
        return _fail(name, "SECRET_PROVIDER=azure but AZURE_KEYVAULT_URL is unset")
    parsed = urlparse(url)
    if not parsed.hostname:
        return _fail(name, f"AZURE_KEYVAULT_URL unparseable: {url}")
    import socket

    try:
        socket.gethostbyname(parsed.hostname)
        return _pass(name, f"DNS ok: {parsed.hostname}")
    except OSError as exc:
        return _fail(name, f"DNS resolution failed: {exc}")


def check_otel_endpoint() -> CheckResult:
    """When OTEL_EXPORTER_OTLP_ENDPOINT is set, confirm it parses + DNS-resolves."""
    name = "otel-exporter"
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        return _skip(name, "OTEL_EXPORTER_OTLP_ENDPOINT not set (tracing disabled)")
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.hostname:
        return _fail(name, f"unparseable endpoint: {endpoint}")
    import socket

    try:
        socket.gethostbyname(parsed.hostname)
        return _pass(name, endpoint)
    except OSError as exc:
        return _warn(name, f"DNS resolution failed for {parsed.hostname}: {exc}")


def check_execution_modes() -> CheckResult:
    """Production-safety gate. Loudly warn if 'live' appears in dev/test envs.

    This is a *configuration sanity* check, not a service probe — but it
    deserves to run alongside the others so an accidental dev-machine
    "ALLOWED_EXECUTION_MODES=live" cannot pass review unflagged.
    """
    name = "exec-modes"
    modes = os.environ.get("ALLOWED_EXECUTION_MODES", "")
    if not modes:
        return _skip(name, "ALLOWED_EXECUTION_MODES not set (default policy applies)")
    parts = [p.strip() for p in modes.split(",") if p.strip()]
    valid = {"shadow", "paper", "live"}
    unknown = [p for p in parts if p not in valid]
    if unknown:
        return _fail(name, f"unknown modes: {unknown} (valid: {sorted(valid)})")
    env = os.environ.get("ENVIRONMENT", "development").lower()
    if "live" in parts and env in ("development", "dev", "test", "testing"):
        return _warn(
            name,
            f"'live' enabled in ENVIRONMENT={env} — set ALLOWED_EXECUTION_MODES=shadow,paper for dev",
        )
    return _pass(name, f"{','.join(parts)} (ENVIRONMENT={env})")


# -------------------------- registry + entrypoint ----------------------------


CHECKS: list[Callable[[], CheckResult]] = [
    check_postgres,
    check_redis,
    check_minio,
    check_keycloak,
    check_jwt_secret,
    check_celery_broker,
    check_azure_keyvault,
    check_otel_endpoint,
    check_execution_modes,
]


def run_checks() -> list[CheckResult]:
    """Public entry point — exposed so tests can call it directly."""
    return [chk() for chk in CHECKS]


def _print_results(results: list[CheckResult]) -> None:
    width = max((len(r.name) for r in results), default=8)
    for r in results:
        marker = {"PASS": "✓", "FAIL": "✗", "SKIP": "·", "WARN": "!"}.get(r.status, "?")
        print(f"  [{r.status:<4}] {marker} {r.name:<{width}}  {r.detail}")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    _load_dotenv(repo_root / ".env")
    results = run_checks()
    _print_results(results)
    if any(r.status == "FAIL" for r in results):
        return 1
    if any(r.status == "WARN" for r in results):
        return 3
    if any(r.status == "SKIP" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
