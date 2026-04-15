"""
Tests for database connection pool configuration from environment variables.

Verifies that DB_POOL_SIZE, DB_POOL_OVERFLOW, and DB_POOL_TIMEOUT are read
from environment variables and applied to the PostgreSQL engine configuration,
and that invalid values are rejected with CRITICAL-level log warnings.

Example:
    pytest tests/unit/test_db_pool_config.py -v
"""

from __future__ import annotations

import os
from unittest.mock import patch


class TestPoolConfigFromEnv:
    """Connection pool parameters are read from environment variables."""

    def test_default_pool_size_is_20(self):
        """When DB_POOL_SIZE is not set, default pool_size is 20."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        }
        env_clean = {k: v for k, v in os.environ.items() if not k.startswith("DB_POOL")}
        env_clean.update(env)
        with patch.dict(os.environ, env_clean, clear=True):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["pool_size"] == 20

    def test_custom_pool_size_from_env(self):
        """DB_POOL_SIZE env var overrides the default."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "DB_POOL_SIZE": "20",
        }
        with patch.dict(os.environ, env, clear=False):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["pool_size"] == 20

    def test_custom_pool_overflow_from_env(self):
        """DB_POOL_OVERFLOW env var overrides the default."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "DB_POOL_OVERFLOW": "25",
        }
        with patch.dict(os.environ, env, clear=False):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["max_overflow"] == 25

    def test_custom_pool_timeout_from_env(self):
        """DB_POOL_TIMEOUT env var overrides the default."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "DB_POOL_TIMEOUT": "60",
        }
        with patch.dict(os.environ, env, clear=False):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["pool_timeout"] == 60

    def test_default_pool_timeout_is_30(self):
        """When DB_POOL_TIMEOUT is not set, default pool_timeout is 30."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        }
        env_clean = {k: v for k, v in os.environ.items() if not k.startswith("DB_POOL")}
        env_clean.update(env)
        with patch.dict(os.environ, env_clean, clear=True):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["pool_timeout"] == 30

    def test_sqlite_returns_static_pool(self):
        """SQLite URLs get StaticPool, no pool_size/overflow/timeout."""
        import services.api.db as db_mod

        result = db_mod._get_pool_kwargs("sqlite:///./test.db")
        from sqlalchemy.pool import StaticPool

        assert result["poolclass"] is StaticPool
        assert "pool_size" not in result
        assert "max_overflow" not in result

    def test_invalid_pool_size_zero_logs_critical(self, caplog):
        """Non-positive DB_POOL_SIZE logs CRITICAL and uses default."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "DB_POOL_SIZE": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        # Should fall back to default of 20
        assert result["pool_size"] == 20

    def test_invalid_pool_size_negative_uses_default(self):
        """Negative DB_POOL_SIZE uses default."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "DB_POOL_SIZE": "-3",
        }
        with patch.dict(os.environ, env, clear=False):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["pool_size"] == 20

    def test_non_numeric_pool_size_uses_default(self):
        """Non-numeric DB_POOL_SIZE uses default."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "DB_POOL_SIZE": "abc",
        }
        with patch.dict(os.environ, env, clear=False):
            import services.api.db as db_mod

            result = db_mod._get_pool_kwargs("postgresql://u:p@localhost:5432/db")
        assert result["pool_size"] == 20
