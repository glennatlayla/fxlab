"""
Tests for SecretProvider interface and implementations.

Covers:
- SecretProviderInterface contract
- EnvSecretProvider: reads from os.environ, list_secrets metadata
- MockSecretProvider: in-memory, supports rotate_secret
- SecretMetadata contract

Example:
    pytest tests/unit/test_secret_provider.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from libs.contracts.interfaces.secret_provider import (
    SecretMetadata,
    SecretProviderInterface,
)
from libs.contracts.mocks.mock_secret_provider import MockSecretProvider
from services.api.infrastructure.env_secret_provider import EnvSecretProvider

# ---------------------------------------------------------------------------
# EnvSecretProvider
# ---------------------------------------------------------------------------


class TestEnvSecretProvider:
    """EnvSecretProvider reads secrets from os.environ."""

    def test_get_secret_returns_env_value(self):
        """get_secret returns the environment variable value."""
        with patch.dict(os.environ, {"TEST_SECRET": "my-secret-value"}):
            provider = EnvSecretProvider()
            assert provider.get_secret("TEST_SECRET") == "my-secret-value"

    def test_get_secret_raises_on_missing(self):
        """get_secret raises KeyError when variable is not set."""
        env_clean = {k: v for k, v in os.environ.items() if k != "MISSING_SECRET"}
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            with pytest.raises(KeyError, match="MISSING_SECRET"):
                provider.get_secret("MISSING_SECRET")

    def test_get_secret_or_default_returns_value(self):
        """get_secret_or_default returns the env var when present."""
        with patch.dict(os.environ, {"TEST_SECRET": "real"}):
            provider = EnvSecretProvider()
            assert provider.get_secret_or_default("TEST_SECRET", "fallback") == "real"

    def test_get_secret_or_default_returns_default(self):
        """get_secret_or_default returns default when variable is missing."""
        env_clean = {k: v for k, v in os.environ.items() if k != "MISSING_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            assert provider.get_secret_or_default("MISSING_KEY", "fallback") == "fallback"

    def test_rotate_secret_raises_when_new_suffix_missing(self):
        """rotate_secret raises KeyError when KEY_NEW is not in env."""
        env_clean = {k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY_NEW"}
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            with pytest.raises(KeyError, match="JWT_SECRET_KEY_NEW"):
                provider.rotate_secret("JWT_SECRET_KEY", "new-value")

    def test_list_secrets_returns_metadata(self):
        """list_secrets returns metadata for known secret keys."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "abc", "DATABASE_URL": "pg://"}):
            provider = EnvSecretProvider()
            secrets = provider.list_secrets()
            keys = [s.key for s in secrets]
            assert "JWT_SECRET_KEY" in keys
            assert "DATABASE_URL" in keys

    def test_list_secrets_marks_missing_as_not_set(self):
        """Secrets not present in env are marked as not set."""
        env_clean = {k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY"}
        with patch.dict(os.environ, env_clean, clear=True):
            provider = EnvSecretProvider()
            secrets = provider.list_secrets()
            jwt_meta = next((s for s in secrets if s.key == "JWT_SECRET_KEY"), None)
            assert jwt_meta is not None
            assert jwt_meta.is_set is False

    def test_implements_interface(self):
        """EnvSecretProvider is a proper implementation of SecretProviderInterface."""
        provider = EnvSecretProvider()
        assert isinstance(provider, SecretProviderInterface)


# ---------------------------------------------------------------------------
# MockSecretProvider
# ---------------------------------------------------------------------------


class TestMockSecretProvider:
    """MockSecretProvider stores secrets in memory for testing."""

    def test_create_with_initial_secrets(self):
        """Constructor accepts initial secret dict."""
        provider = MockSecretProvider({"KEY1": "val1", "KEY2": "val2"})
        assert provider.get_secret("KEY1") == "val1"
        assert provider.get_secret("KEY2") == "val2"

    def test_get_secret_raises_on_missing(self):
        """get_secret raises KeyError for unknown keys."""
        provider = MockSecretProvider({})
        with pytest.raises(KeyError):
            provider.get_secret("NONEXISTENT")

    def test_get_secret_or_default(self):
        """get_secret_or_default falls back to default."""
        provider = MockSecretProvider({})
        assert provider.get_secret_or_default("MISSING", "default") == "default"

    def test_rotate_secret(self):
        """rotate_secret updates the stored value."""
        provider = MockSecretProvider({"KEY": "old"})
        provider.rotate_secret("KEY", "new")
        assert provider.get_secret("KEY") == "new"

    def test_rotate_secret_records_timestamp(self):
        """rotate_secret records the rotation timestamp."""
        provider = MockSecretProvider({"KEY": "old"})
        provider.rotate_secret("KEY", "new")
        secrets = provider.list_secrets()
        meta = next(s for s in secrets if s.key == "KEY")
        assert meta.last_rotated is not None

    def test_rotate_secret_creates_new_key(self):
        """rotate_secret can create a key that didn't exist before."""
        provider = MockSecretProvider({})
        provider.rotate_secret("NEW_KEY", "value")
        assert provider.get_secret("NEW_KEY") == "value"

    def test_list_secrets_returns_all(self):
        """list_secrets returns metadata for all stored secrets."""
        provider = MockSecretProvider({"A": "1", "B": "2"})
        secrets = provider.list_secrets()
        assert len(secrets) == 2
        assert all(s.is_set for s in secrets)

    def test_implements_interface(self):
        """MockSecretProvider is a proper implementation of SecretProviderInterface."""
        provider = MockSecretProvider({})
        assert isinstance(provider, SecretProviderInterface)

    def test_get_rotation_count(self):
        """Introspection: rotation count tracks how many rotations occurred."""
        provider = MockSecretProvider({"K": "v"})
        assert provider.get_rotation_count() == 0
        provider.rotate_secret("K", "v2")
        assert provider.get_rotation_count() == 1
        provider.rotate_secret("K", "v3")
        assert provider.get_rotation_count() == 2


# ---------------------------------------------------------------------------
# SecretMetadata
# ---------------------------------------------------------------------------


class TestSecretMetadata:
    """SecretMetadata contract validation."""

    def test_create_with_all_fields(self):
        """SecretMetadata accepts all fields."""
        meta = SecretMetadata(
            key="JWT_SECRET_KEY",
            source="environment",
            is_set=True,
            last_rotated=datetime.now(timezone.utc),
            description="JWT signing key",
        )
        assert meta.key == "JWT_SECRET_KEY"
        assert meta.is_set is True

    def test_create_minimal(self):
        """SecretMetadata works with just key and source."""
        meta = SecretMetadata(key="DB_URL", source="env", is_set=False)
        assert meta.last_rotated is None
        assert meta.description == ""
