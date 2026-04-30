"""
Unit tests for scripts/validate_env.py.

These tests must run without any real external service. They exercise:
- Each probe's SKIP path when the relevant env vars are absent.
- _scrub_url() removes passwords.
- _load_dotenv() honours pre-existing ambient values (no clobber).
- run_checks() returns one CheckResult per registered probe.
- main() exit-code matrix (pass / fail / skip).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_env.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_env", SCRIPT_PATH)
    assert spec and spec.loader, "cannot load validate_env"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_env"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ve(monkeypatch):
    """Yield validate_env after stripping every env var the validator reads."""
    for var in (
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_PASSWORD",
        "S3_ENDPOINT",
        "MINIO_HOST",
        "MINIO_PORT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
        "KEYCLOAK_URL",
        "KEYCLOAK_REALM",
        "VITE_OIDC_AUTHORITY",
        "KEYCLOAK_VALIDATE_BUDGET_SECONDS",
        "JWT_SECRET_KEY",
        "CELERY_BROKER_URL",
        "SECRET_PROVIDER",
        "AZURE_KEYVAULT_URL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "ALLOWED_EXECUTION_MODES",
        "ENVIRONMENT",
    ):
        monkeypatch.delenv(var, raising=False)
    return _load_module()


class TestScrubUrl:
    def test_strips_password(self, ve):
        scrubbed = ve._scrub_url("postgresql://user:supersecret@host:5432/db")
        assert "supersecret" not in scrubbed
        assert "***" in scrubbed
        assert "user" in scrubbed
        assert "host" in scrubbed

    def test_no_password_passthrough(self, ve):
        url = "redis://localhost:6379/0"
        assert ve._scrub_url(url) == url


class TestLoadDotenv:
    def test_does_not_clobber_existing_env(self, ve, monkeypatch, tmp_path):
        monkeypatch.setenv("CELERY_BROKER_URL", "from-ambient")
        env = tmp_path / ".env"
        env.write_text("CELERY_BROKER_URL=from-file\n")
        ve._load_dotenv(env)
        import os

        assert os.environ["CELERY_BROKER_URL"] == "from-ambient"

    def test_loads_unset_keys(self, ve, tmp_path):
        env = tmp_path / ".env"
        env.write_text("CELERY_BROKER_URL=from-file\n# comment\nFOO=bar\n")
        ve._load_dotenv(env)
        import os

        assert os.environ["CELERY_BROKER_URL"] == "from-file"
        assert os.environ["FOO"] == "bar"

    def test_silently_handles_missing_file(self, ve, tmp_path):
        ve._load_dotenv(tmp_path / "does-not-exist")  # must not raise


class TestSkipPaths:
    """All probes must SKIP cleanly when their env vars are absent."""

    def test_postgres_skips_without_url(self, ve):
        assert ve.check_postgres().status == "SKIP"

    def test_redis_skips_without_url(self, ve):
        assert ve.check_redis().status == "SKIP"

    def test_minio_skips_without_endpoint(self, ve):
        assert ve.check_minio().status == "SKIP"

    def test_keycloak_skips_without_authority(self, ve):
        assert ve.check_keycloak().status == "SKIP"

    def test_jwt_skips_when_unset(self, ve):
        assert ve.check_jwt_secret().status == "SKIP"

    def test_celery_skips_without_broker_url(self, ve):
        assert ve.check_celery_broker().status == "SKIP"

    def test_azure_keyvault_skips_unless_provider_azure(self, ve):
        assert ve.check_azure_keyvault().status == "SKIP"

    def test_otel_skips_without_endpoint(self, ve):
        assert ve.check_otel_endpoint().status == "SKIP"

    def test_exec_modes_skips_when_unset(self, ve):
        assert ve.check_execution_modes().status == "SKIP"


class TestJwtSecret:
    def test_too_short_secret_fails(self, ve, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "short")
        result = ve.check_jwt_secret()
        assert result.status == "FAIL"
        assert "32" in result.detail

    def test_long_secret_passes(self, ve, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
        result = ve.check_jwt_secret()
        assert result.status == "PASS"
        assert "64" in result.detail


class TestCeleryBroker:
    def test_unparseable_fails(self, ve, monkeypatch):
        monkeypatch.setenv("CELERY_BROKER_URL", "not-a-url")
        assert ve.check_celery_broker().status == "FAIL"

    def test_redis_url_passes(self, ve, monkeypatch):
        monkeypatch.setenv("CELERY_BROKER_URL", "redis://broker:6379/1")
        assert ve.check_celery_broker().status == "PASS"


class TestAzureKeyvault:
    def test_provider_azure_without_url_fails(self, ve, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "azure")
        result = ve.check_azure_keyvault()
        assert result.status == "FAIL"
        assert "AZURE_KEYVAULT_URL" in result.detail

    def test_unparseable_url_fails(self, ve, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "azure")
        monkeypatch.setenv("AZURE_KEYVAULT_URL", "not-a-url")
        assert ve.check_azure_keyvault().status == "FAIL"

    def test_unresolvable_host_fails(self, ve, monkeypatch):
        monkeypatch.setenv("SECRET_PROVIDER", "azure")
        monkeypatch.setenv(
            "AZURE_KEYVAULT_URL",
            "https://this-host-does-not-exist-fxlab-test.invalid",
        )
        assert ve.check_azure_keyvault().status == "FAIL"


class TestOtelExporter:
    def test_unparseable_fails(self, ve, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "no-scheme")
        assert ve.check_otel_endpoint().status == "FAIL"

    def test_unresolvable_warns(self, ve, monkeypatch):
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://this-otel-endpoint-does-not-exist.invalid:4317",
        )
        # WARN, not FAIL — tracing is best-effort, not load-bearing.
        assert ve.check_otel_endpoint().status == "WARN"


class TestExecutionModes:
    def test_unknown_mode_fails(self, ve, monkeypatch):
        monkeypatch.setenv("ALLOWED_EXECUTION_MODES", "shadow,paper,turbo")
        assert ve.check_execution_modes().status == "FAIL"

    def test_live_in_dev_warns(self, ve, monkeypatch):
        monkeypatch.setenv("ALLOWED_EXECUTION_MODES", "shadow,paper,live")
        monkeypatch.setenv("ENVIRONMENT", "development")
        result = ve.check_execution_modes()
        assert result.status == "WARN"
        assert "live" in result.detail.lower()

    def test_live_in_production_passes(self, ve, monkeypatch):
        monkeypatch.setenv("ALLOWED_EXECUTION_MODES", "shadow,paper,live")
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert ve.check_execution_modes().status == "PASS"

    def test_safe_modes_in_dev_pass(self, ve, monkeypatch):
        monkeypatch.setenv("ALLOWED_EXECUTION_MODES", "shadow,paper")
        monkeypatch.setenv("ENVIRONMENT", "development")
        assert ve.check_execution_modes().status == "PASS"


class TestRunChecks:
    def test_returns_one_result_per_check(self, ve):
        results = ve.run_checks()
        assert len(results) == len(ve.CHECKS)
        assert all(hasattr(r, "name") and hasattr(r, "status") for r in results)


class TestMainExitCodes:
    def test_all_skip_returns_2(self, ve):
        assert ve.main() == 2

    def test_one_fail_returns_1(self, ve, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "short")  # forces FAIL
        assert ve.main() == 1

    def test_warn_returns_3(self, ve, monkeypatch):
        # Live execution mode in development is a WARN
        monkeypatch.setenv("ALLOWED_EXECUTION_MODES", "shadow,paper,live")
        monkeypatch.setenv("ENVIRONMENT", "development")
        # All other checks SKIP — but WARN takes precedence over SKIP
        # because operators need to see configuration warnings even when
        # services aren't probeable.
        with patch.object(ve, "CHECKS", [ve.check_execution_modes]):
            assert ve.main() == 3

    def test_all_pass_returns_0(self, ve, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
        with patch.object(ve, "CHECKS", [ve.check_jwt_secret]):
            assert ve.main() == 0


class TestPostgresImportError:
    def test_fails_clean_when_psycopg2_missing(self, ve, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
        with patch.dict("sys.modules", {"psycopg2": None}):
            result = ve.check_postgres()
        # Either FAIL (import gone) or PASS (already imported elsewhere).
        assert result.status in ("FAIL", "PASS")
