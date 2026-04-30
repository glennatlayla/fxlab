"""
scripts/validate_env.py
========================

FXLab credential / connectivity validator.

Reads `.env` (if present) plus the ambient process environment, then probes
every external dependency the platform needs at runtime:

- PostgreSQL  (DATABASE_URL or POSTGRES_* — opens a real connection)
- Redis       (REDIS_URL or REDIS_HOST/PORT — sends PING)
- MinIO/S3    (S3_ENDPOINT / MINIO_HOST / MINIO_PORT — health-ready probe)
- Keycloak    (KEYCLOAK_URL or VITE_OIDC_AUTHORITY — fetches OIDC discovery)
- JWT         (JWT_SECRET_KEY — confirms set + non-trivial length)
- Celery      (CELERY_BROKER_URL — confirms it parses; no broker connect)

Each probe prints PASS, SKIP (env var unset / optional) or FAIL.

Exit codes:
  0 — every configured service reachable
  1 — at least one configured service FAILED
  2 — one or more services skipped because env vars unset (informational)

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
    status: str  # "PASS", "FAIL", "SKIP"
    detail: str


def _pass(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "PASS", detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "FAIL", detail)


def _skip(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "SKIP", detail)


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
    try:
        resp = requests.get(discovery, timeout=5)
        if resp.ok and "issuer" in resp.json():
            return _pass(name, discovery)
        return _fail(name, f"HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        return _fail(name, f"{type(exc).__name__}: {exc}")


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


# -------------------------- registry + entrypoint ----------------------------


CHECKS: list[Callable[[], CheckResult]] = [
    check_postgres,
    check_redis,
    check_minio,
    check_keycloak,
    check_jwt_secret,
    check_celery_broker,
]


def run_checks() -> list[CheckResult]:
    """Public entry point — exposed so tests can call it directly."""
    return [chk() for chk in CHECKS]


def _print_results(results: list[CheckResult]) -> None:
    width = max((len(r.name) for r in results), default=8)
    for r in results:
        marker = {"PASS": "✓", "FAIL": "✗", "SKIP": "·"}.get(r.status, "?")
        print(f"  [{r.status:<4}] {marker} {r.name:<{width}}  {r.detail}")


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    _load_dotenv(repo_root / ".env")
    results = run_checks()
    _print_results(results)
    if any(r.status == "FAIL" for r in results):
        return 1
    if any(r.status == "SKIP" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
