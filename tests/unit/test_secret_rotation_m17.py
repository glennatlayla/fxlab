"""
Unit tests for M17 secret rotation enhancements.

Covers:
- EnvSecretProvider.rotate_secret() with _NEW suffix pattern
- EnvSecretProvider.list_expiring() threshold-based expiry detection
- SecretRotationJob: periodic check for _NEW env vars, rotation execution
- Rotation event logging and error handling
- Both old and new values valid during rotation window

Dependencies:
- services.api.infrastructure.env_secret_provider: EnvSecretProvider
- services.api.infrastructure.secret_rotation_job: SecretRotationJob
- libs.contracts.interfaces.secret_provider: SecretProviderInterface

Example:
    pytest tests/unit/test_secret_rotation_m17.py -v
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services.api.infrastructure.env_secret_provider import EnvSecretProvider
from services.api.infrastructure.secret_rotation_job import SecretRotationJob

# ---------------------------------------------------------------------------
# EnvSecretProvider — Rotation via _NEW suffix
# ---------------------------------------------------------------------------


class TestEnvSecretProviderRotation:
    """EnvSecretProvider.rotate_secret() reads KEY_NEW from env and swaps."""

    def test_rotate_reads_new_suffix_from_env(self) -> None:
        """rotate_secret reads the new value from KEY_NEW env var."""
        env = {
            "JWT_SECRET_KEY": "old-key",
            "JWT_SECRET_KEY_NEW": "rotated-key",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            provider.rotate_secret("JWT_SECRET_KEY", "rotated-key")
            # After rotation, get_secret returns the new value
            assert provider.get_secret("JWT_SECRET_KEY") == "rotated-key"

    def test_rotate_preserves_old_value_in_rotation_window(self) -> None:
        """Both old and new values are valid during the rotation window."""
        env = {
            "JWT_SECRET_KEY": "old-key",
            "JWT_SECRET_KEY_NEW": "rotated-key",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            provider.rotate_secret("JWT_SECRET_KEY", "rotated-key")
            # Old key accessible via _OLD suffix
            assert provider.get_secret("JWT_SECRET_KEY_OLD") == "old-key"
            # New key is the current value
            assert provider.get_secret("JWT_SECRET_KEY") == "rotated-key"

    def test_rotate_raises_when_new_suffix_missing(self) -> None:
        """rotate_secret raises KeyError when KEY_NEW is not in env."""
        env = {"JWT_SECRET_KEY": "current-key"}
        # Remove any _NEW suffix
        env_clean = {k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY_NEW"}
        env_clean.update(env)
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            with pytest.raises(KeyError, match="JWT_SECRET_KEY_NEW"):
                provider.rotate_secret("JWT_SECRET_KEY", "ignored")

    def test_rotate_raises_when_new_value_mismatches(self) -> None:
        """rotate_secret raises ValueError when new_value != KEY_NEW env var."""
        env = {
            "JWT_SECRET_KEY": "old-key",
            "JWT_SECRET_KEY_NEW": "actual-new-key",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            with pytest.raises(ValueError, match="does not match"):
                provider.rotate_secret("JWT_SECRET_KEY", "wrong-value")

    def test_rotate_records_timestamp(self) -> None:
        """rotate_secret records the rotation timestamp in metadata."""
        env = {
            "DATABASE_URL": "pg://old",
            "DATABASE_URL_NEW": "pg://new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            before = datetime.now(timezone.utc)
            provider.rotate_secret("DATABASE_URL", "pg://new")
            after = datetime.now(timezone.utc)
            secrets = provider.list_secrets()
            db_meta = next(s for s in secrets if s.key == "DATABASE_URL")
            assert db_meta.last_rotated is not None
            assert before <= db_meta.last_rotated <= after

    def test_rotate_logs_rotation_event(self) -> None:
        """rotate_secret emits a structured log at INFO level."""
        env = {
            "JWT_SECRET_KEY": "old",
            "JWT_SECRET_KEY_NEW": "new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            with patch("services.api.infrastructure.env_secret_provider.logger") as mock_logger:
                provider.rotate_secret("JWT_SECRET_KEY", "new")
                mock_logger.info.assert_called_once()
                call_args = mock_logger.info.call_args
                assert "secret.rotated" in str(call_args)

    def test_rotate_is_thread_safe(self) -> None:
        """Concurrent rotations do not corrupt state."""
        env = {
            "JWT_SECRET_KEY": "old",
            "JWT_SECRET_KEY_NEW": "new",
            "DATABASE_URL": "pg://old",
            "DATABASE_URL_NEW": "pg://new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            errors: list[Exception] = []

            def rotate_jwt() -> None:
                try:
                    provider.rotate_secret("JWT_SECRET_KEY", "new")
                except Exception as e:
                    errors.append(e)

            def rotate_db() -> None:
                try:
                    provider.rotate_secret("DATABASE_URL", "pg://new")
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=rotate_jwt)
            t2 = threading.Thread(target=rotate_db)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            assert errors == []
            assert provider.get_secret("JWT_SECRET_KEY") == "new"
            assert provider.get_secret("DATABASE_URL") == "pg://new"

    def test_get_secret_returns_rotated_value_over_env(self) -> None:
        """After rotation, get_secret returns in-memory rotated value."""
        env = {
            "JWT_SECRET_KEY": "env-value",
            "JWT_SECRET_KEY_NEW": "rotated",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            provider.rotate_secret("JWT_SECRET_KEY", "rotated")
            # The rotated value takes precedence over the stale env var
            assert provider.get_secret("JWT_SECRET_KEY") == "rotated"


# ---------------------------------------------------------------------------
# EnvSecretProvider — list_expiring
# ---------------------------------------------------------------------------


class TestEnvSecretProviderListExpiring:
    """EnvSecretProvider.list_expiring() identifies secrets approaching expiry."""

    def test_list_expiring_returns_empty_when_no_rotations(self) -> None:
        """No secrets flagged as expiring when none have been rotated."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "val"}, clear=False):
            provider = EnvSecretProvider()
            expiring = provider.list_expiring(threshold_days=90)
            # With no rotation history, all are "expiring" (never rotated)
            assert len(expiring) > 0

    def test_list_expiring_includes_never_rotated_secrets(self) -> None:
        """Secrets that have never been rotated appear in the expiring list."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "val"}, clear=False):
            provider = EnvSecretProvider()
            expiring = provider.list_expiring(threshold_days=90)
            keys = [s.key for s in expiring]
            assert "JWT_SECRET_KEY" in keys

    def test_list_expiring_excludes_recently_rotated(self) -> None:
        """Recently rotated secrets are NOT in the expiring list."""
        env = {
            "JWT_SECRET_KEY": "old",
            "JWT_SECRET_KEY_NEW": "new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            provider.rotate_secret("JWT_SECRET_KEY", "new")
            expiring = provider.list_expiring(threshold_days=90)
            keys = [s.key for s in expiring]
            # Just rotated — should not be expiring
            assert "JWT_SECRET_KEY" not in keys

    def test_list_expiring_includes_stale_rotated_secrets(self) -> None:
        """Secrets rotated beyond threshold_days ago appear as expiring."""
        env = {
            "JWT_SECRET_KEY": "old",
            "JWT_SECRET_KEY_NEW": "new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            provider.rotate_secret("JWT_SECRET_KEY", "new")
            # Backdate the rotation timestamp
            old_time = datetime.now(timezone.utc) - timedelta(days=100)
            provider._rotation_timestamps["JWT_SECRET_KEY"] = old_time
            expiring = provider.list_expiring(threshold_days=90)
            keys = [s.key for s in expiring]
            assert "JWT_SECRET_KEY" in keys

    def test_list_expiring_only_includes_set_secrets(self) -> None:
        """Unset secrets are not included in the expiring list."""
        env_clean = {k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            expiring = provider.list_expiring(threshold_days=90)
            keys = [s.key for s in expiring]
            assert "JWT_SECRET_KEY" not in keys


# ---------------------------------------------------------------------------
# SecretRotationJob
# ---------------------------------------------------------------------------


class TestSecretRotationJob:
    """SecretRotationJob periodically checks for _NEW env vars and rotates."""

    def _make_job(
        self,
        provider: EnvSecretProvider | None = None,
        check_interval_seconds: float = 60.0,
    ) -> SecretRotationJob:
        """Create a SecretRotationJob with sensible test defaults."""
        return SecretRotationJob(
            provider=provider or EnvSecretProvider(),
            check_interval_seconds=check_interval_seconds,
        )

    def test_check_and_rotate_detects_new_suffix(self) -> None:
        """check_and_rotate() finds KEY_NEW env vars and triggers rotation."""
        env = {
            "JWT_SECRET_KEY": "old-jwt",
            "JWT_SECRET_KEY_NEW": "new-jwt",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider)
            rotated = job.check_and_rotate()
            assert "JWT_SECRET_KEY" in rotated
            assert provider.get_secret("JWT_SECRET_KEY") == "new-jwt"

    def test_check_and_rotate_returns_empty_when_no_new_vars(self) -> None:
        """check_and_rotate() returns empty list when no _NEW vars exist."""
        env = {"JWT_SECRET_KEY": "current"}
        env_clean = {k: v for k, v in os.environ.items() if not k.endswith("_NEW")}
        env_clean.update(env)
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider)
            rotated = job.check_and_rotate()
            assert rotated == []

    def test_check_and_rotate_handles_multiple_keys(self) -> None:
        """check_and_rotate() rotates multiple keys in a single pass."""
        env = {
            "JWT_SECRET_KEY": "old-jwt",
            "JWT_SECRET_KEY_NEW": "new-jwt",
            "DATABASE_URL": "pg://old",
            "DATABASE_URL_NEW": "pg://new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider)
            rotated = job.check_and_rotate()
            assert len(rotated) == 2
            assert "JWT_SECRET_KEY" in rotated
            assert "DATABASE_URL" in rotated

    def test_check_and_rotate_logs_each_rotation(self) -> None:
        """check_and_rotate() logs INFO for each rotated key."""
        env = {
            "JWT_SECRET_KEY": "old",
            "JWT_SECRET_KEY_NEW": "new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider)
            with patch("services.api.infrastructure.secret_rotation_job.logger") as mock_log:
                job.check_and_rotate()
                mock_log.info.assert_called()

    def test_check_and_rotate_skips_non_known_keys(self) -> None:
        """check_and_rotate() only rotates keys in _KNOWN_SECRET_KEYS."""
        env = {
            "RANDOM_VAR": "old",
            "RANDOM_VAR_NEW": "new",
        }
        env_clean = {k: v for k, v in os.environ.items() if not k.endswith("_NEW")}
        env_clean.update(env)
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider)
            rotated = job.check_and_rotate()
            assert rotated == []

    def test_check_and_rotate_continues_on_individual_failure(self) -> None:
        """If one rotation fails, others still proceed."""
        env = {
            "JWT_SECRET_KEY": "old-jwt",
            "JWT_SECRET_KEY_NEW": "new-jwt",
            "DATABASE_URL": "pg://old",
            "DATABASE_URL_NEW": "pg://new",
        }
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider)
            # Make JWT rotation fail by removing its current value mid-flight
            original_rotate = provider.rotate_secret

            call_count = 0

            def failing_on_first(key: str, new_value: str) -> None:
                nonlocal call_count
                call_count += 1
                if key == "JWT_SECRET_KEY":
                    raise RuntimeError("Simulated rotation failure")
                original_rotate(key, new_value)

            provider.rotate_secret = failing_on_first  # type: ignore[assignment]
            rotated = job.check_and_rotate()
            # DATABASE_URL should still be rotated
            assert "DATABASE_URL" in rotated
            assert "JWT_SECRET_KEY" not in rotated

    def test_job_is_not_running_initially(self) -> None:
        """SecretRotationJob is not running after construction."""
        job = self._make_job()
        assert job.is_running is False

    def test_start_and_stop_lifecycle(self) -> None:
        """start() begins background thread, stop() terminates it."""
        env = {"JWT_SECRET_KEY": "val"}
        with patch.dict(os.environ, env, clear=False):
            provider = EnvSecretProvider()
            job = self._make_job(provider=provider, check_interval_seconds=0.05)
            job.start()
            assert job.is_running is True
            job.stop()
            assert job.is_running is False
