"""
Unit tests for production localhost fail-fast guards (INFRA-6).

Purpose:
    Verify that services which depend on external infrastructure (Redis,
    Celery broker) fail fast with a clear error in production environments
    instead of silently falling back to localhost URLs that don't exist
    in containerised deployments.

Responsibilities:
    - Verify rate_limit._create_backend raises in production when REDIS_URL
      is unset and RATE_LIMIT_BACKEND=redis.
    - Verify CeleryQueueRepository logs a warning when using localhost fallback
      in production.
    - Verify non-production environments retain the localhost fallback
      (developer ergonomics).

Does NOT:
    - Test actual Redis/Celery connectivity.
    - Test full middleware dispatch flow.

Dependencies:
    - services.api.middleware.rate_limit: _create_backend factory.
    - services.api.repositories.celery_queue_repository: CeleryQueueRepository.
    - unittest.mock: For environment variable patching.

Example:
    pytest tests/unit/test_localhost_failfast.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestRateLimitLocalhostGuard:
    """Verify rate limit backend rejects localhost in production."""

    def test_redis_backend_requires_redis_url_in_production(self) -> None:
        """RATE_LIMIT_BACKEND=redis without REDIS_URL should raise in production."""
        from services.api.middleware.rate_limit import _create_backend

        env = {
            "RATE_LIMIT_BACKEND": "redis",
            "ENVIRONMENT": "production",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REDIS_URL", None)
            with pytest.raises(
                RuntimeError,
                match="REDIS_URL.*required.*production",
            ):
                _create_backend()

    def test_redis_backend_allows_localhost_in_development(self) -> None:
        """RATE_LIMIT_BACKEND=redis without REDIS_URL should fallback in dev."""
        from services.api.middleware.rate_limit import InMemoryRateLimitBackend, _create_backend

        mock_redis_module = MagicMock()
        mock_redis_module.Redis.from_url.side_effect = ConnectionError("refused")

        env = {
            "RATE_LIMIT_BACKEND": "redis",
            "ENVIRONMENT": "development",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REDIS_URL", None)
            with patch.dict("sys.modules", {"redis": mock_redis_module}):
                backend = _create_backend()
                # Falls back to in-memory (graceful degradation in dev)
                assert isinstance(backend, InMemoryRateLimitBackend)

    def test_redis_backend_allows_explicit_url_in_production(self) -> None:
        """RATE_LIMIT_BACKEND=redis with explicit REDIS_URL should work in production."""
        from services.api.middleware.rate_limit import RedisRateLimitBackend, _create_backend

        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.Redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True

        env = {
            "RATE_LIMIT_BACKEND": "redis",
            "ENVIRONMENT": "production",
            "REDIS_URL": "redis://redis-cluster:6379/0",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.dict("sys.modules", {"redis": mock_redis_module}):
                backend = _create_backend()
                assert isinstance(backend, RedisRateLimitBackend)


class TestCeleryLocalhostGuard:
    """Verify Celery queue repository warns about localhost in production."""

    def test_celery_warns_on_localhost_fallback_in_production(self) -> None:
        """CeleryQueueRepository should raise RuntimeError for localhost in production."""
        import importlib

        import services.api.repositories.celery_queue_repository as cqr_mod

        env = {
            "ENVIRONMENT": "production",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REDIS_URL", None)
            # Reimport the module so __init__ picks up new env vars
            importlib.reload(cqr_mod)
            with pytest.raises(
                RuntimeError,
                match="REDIS_URL.*required.*production",
            ):
                cqr_mod.CeleryQueueRepository()

    def test_celery_allows_localhost_in_development(self) -> None:
        """CeleryQueueRepository should allow localhost fallback in development."""
        import importlib

        import services.api.repositories.celery_queue_repository as cqr_mod

        env = {
            "ENVIRONMENT": "development",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REDIS_URL", None)
            importlib.reload(cqr_mod)
            # Should not raise — localhost fallback is OK in dev
            repo = cqr_mod.CeleryQueueRepository()
            # Repository is initialised (possibly degraded if no local Redis)
            assert repo is not None
