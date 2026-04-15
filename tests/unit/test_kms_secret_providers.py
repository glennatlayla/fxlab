"""
Unit tests for secret provider backends (Azure Key Vault) and factory.

Validates:
- AzureKeyVaultSecretProvider: Key Vault integration, caching, naming, error handling
- SecretProviderFactory: provider selection and construction

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.interfaces.secret_provider import (
    SecretMetadata,
    SecretProviderInterface,
)
from services.api.infrastructure.env_secret_provider import EnvSecretProvider
from services.api.infrastructure.secret_provider_factory import (
    get_provider,
    set_provider,
)

# ============================================================================
# AzureKeyVaultSecretProvider Tests
# ============================================================================


class TestAzureKeyVaultSecretProvider:
    """Tests for AzureKeyVaultSecretProvider (Azure Key Vault integration)."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Reset provider factory to default before/after each test."""
        original_provider = get_provider()
        yield
        set_provider(original_provider)

    @pytest.fixture
    def mock_azure(self):
        """
        Mock Azure SDK modules for Key Vault tests.

        Patches:
        - DefaultAzureCredential (auth)
        - SecretClient (Key Vault access)
        - Azure exception classes

        Returns a dict with mock_credential_cls, mock_client_cls, and mock_client.
        """
        with (
            patch(
                "services.api.infrastructure.azure_keyvault_secret_provider._AZURE_AVAILABLE",
                True,
            ),
            patch(
                "services.api.infrastructure.azure_keyvault_secret_provider.DefaultAzureCredential"
            ) as mock_cred_cls,
            patch(
                "services.api.infrastructure.azure_keyvault_secret_provider.SecretClient"
            ) as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_cred = MagicMock()
            mock_cred_cls.return_value = mock_cred

            yield {
                "credential_cls": mock_cred_cls,
                "credential": mock_cred,
                "client_cls": mock_client_cls,
                "client": mock_client,
            }

    def test_get_secret_from_keyvault_success(self, mock_azure):
        """Test successful secret retrieval from Azure Key Vault."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = "my-secret-value"
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )
        result = provider.get_secret("DATABASE_URL")

        assert result == "my-secret-value"
        # Key should be converted: DATABASE_URL -> fxlab-database-url
        mock_azure["client"].get_secret.assert_called_once_with("fxlab-database-url")

    def test_get_secret_name_conversion(self, mock_azure):
        """Test that logical key names are converted to Key Vault format."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = "secret-key-value"
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )
        provider.get_secret("JWT_SECRET_KEY")

        # JWT_SECRET_KEY -> fxlab-jwt-secret-key
        mock_azure["client"].get_secret.assert_called_once_with("fxlab-jwt-secret-key")

    def test_get_secret_cache_hit(self, mock_azure):
        """Test that cached secrets are returned without API call."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = "cached-value"
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
            cache_ttl_seconds=300,
        )

        # First call — fetches from Key Vault
        result1 = provider.get_secret("REDIS_URL")
        assert result1 == "cached-value"
        assert mock_azure["client"].get_secret.call_count == 1

        # Second call — cache hit, no additional API call
        result2 = provider.get_secret("REDIS_URL")
        assert result2 == "cached-value"
        assert mock_azure["client"].get_secret.call_count == 1

    def test_get_secret_cache_expiry(self, mock_azure):
        """Test that cache entries expire after TTL."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = "expired-value"
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
            cache_ttl_seconds=1,
        )

        # First call
        result1 = provider.get_secret("API_KEY")
        assert result1 == "expired-value"

        # Manually expire cache by backdating timestamp
        kv_name = "fxlab-api-key"
        if kv_name in provider._cache:
            old_time = datetime.now(timezone.utc).timestamp() - 2.0
            provider._cache[kv_name] = ("expired-value", old_time)

        # Update mock to return different value
        new_secret = MagicMock()
        new_secret.value = "new-value"
        mock_azure["client"].get_secret.return_value = new_secret

        # Second call should skip cache (expired)
        result2 = provider.get_secret("API_KEY")
        assert result2 == "new-value"
        assert mock_azure["client"].get_secret.call_count == 2

    def test_get_secret_not_found_raises_keyerror(self, mock_azure):
        """Test that missing Key Vault secret raises KeyError."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
            AzureResourceNotFoundError,
        )

        mock_azure["client"].get_secret.side_effect = AzureResourceNotFoundError("Secret not found")

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )

        with pytest.raises(KeyError):
            provider.get_secret("MISSING_SECRET")

    def test_get_secret_empty_value_raises_keyerror(self, mock_azure):
        """Test that a secret with None value raises KeyError."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = None
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )

        with pytest.raises(KeyError):
            provider.get_secret("DISABLED_SECRET")

    def test_get_secret_auth_failure_raises_keyerror(self, mock_azure):
        """Test that authentication failure raises KeyError."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureAuthError,
            AzureKeyVaultSecretProvider,
        )

        mock_azure["client"].get_secret.side_effect = AzureAuthError("Authentication failed")

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )

        with pytest.raises(KeyError):
            provider.get_secret("AUTH_FAIL_SECRET")

    def test_get_secret_or_default_returns_default_when_missing(self, mock_azure):
        """Test get_secret_or_default returns default when secret missing."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
            AzureResourceNotFoundError,
        )

        mock_azure["client"].get_secret.side_effect = AzureResourceNotFoundError("Not found")

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )

        result = provider.get_secret_or_default("MISSING", "default-val")
        assert result == "default-val"

    def test_get_secret_or_default_returns_value_when_present(self, mock_azure):
        """Test get_secret_or_default returns actual value when present."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = "real-value"
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )

        result = provider.get_secret_or_default("EXISTING", "default-val")
        assert result == "real-value"

    def test_rotate_secret_not_implemented(self, mock_azure):
        """Test that rotate_secret raises NotImplementedError."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
        )

        with pytest.raises(NotImplementedError, match="Azure Key Vault rotation"):
            provider.rotate_secret("ANY_KEY", "new-value")

    def test_list_secrets_returns_matching_metadata(self, mock_azure):
        """Test that list_secrets returns metadata for prefix-matching secrets."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        # Simulate Key Vault listing with some matching and non-matching secrets
        prop1 = MagicMock()
        prop1.name = "fxlab-database-url"
        prop1.enabled = True
        prop1.updated_on = datetime(2026, 4, 1, tzinfo=timezone.utc)
        prop1.content_type = "connection-string"

        prop2 = MagicMock()
        prop2.name = "fxlab-jwt-secret-key"
        prop2.enabled = True
        prop2.updated_on = datetime(2026, 3, 15, tzinfo=timezone.utc)
        prop2.content_type = ""

        prop3 = MagicMock()
        prop3.name = "other-app-secret"
        prop3.enabled = True
        prop3.updated_on = None
        prop3.content_type = ""

        mock_azure["client"].list_properties_of_secrets.return_value = [
            prop1,
            prop2,
            prop3,
        ]

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )

        result = provider.list_secrets()

        # Should only include fxlab-prefixed secrets
        assert len(result) == 2
        assert all(isinstance(m, SecretMetadata) for m in result)

        keys = {m.key for m in result}
        assert "DATABASE_URL" in keys
        assert "JWT_SECRET_KEY" in keys

    def test_custom_credential_used_when_provided(self, mock_azure):
        """Test that a custom credential object is used instead of DefaultAzureCredential."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        custom_cred = MagicMock()

        AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            credential=custom_cred,
        )

        # Should have used custom credential, not DefaultAzureCredential
        mock_azure["client_cls"].assert_called_once_with(
            vault_url="https://fxlab-prod.vault.azure.net",
            credential=custom_cred,
        )

    def test_empty_vault_url_raises_valueerror(self, mock_azure):
        """Test that empty vault_url raises ValueError."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        with pytest.raises(ValueError, match="vault_url is required"):
            AzureKeyVaultSecretProvider(vault_url="")

    def test_vault_url_trailing_slash_stripped(self, mock_azure):
        """Test that trailing slash is removed from vault_url."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net/",
        )

        assert provider._vault_url == "https://fxlab-prod.vault.azure.net"

    def test_default_prefix(self, mock_azure):
        """Test that the default prefix is 'fxlab-'."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        mock_secret = MagicMock()
        mock_secret.value = "test"
        mock_azure["client"].get_secret.return_value = mock_secret

        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
        )
        provider.get_secret("TEST_KEY")

        mock_azure["client"].get_secret.assert_called_once_with("fxlab-test-key")


# ============================================================================
# Key Vault Name Conversion Tests
# ============================================================================


class TestKeyVaultNameConversion:
    """Tests for the _to_keyvault_name helper function."""

    def test_underscores_to_hyphens(self):
        """Test that underscores are converted to hyphens."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            _to_keyvault_name,
        )

        assert _to_keyvault_name("DATABASE_URL") == "database-url"

    def test_lowercased(self):
        """Test that result is lowercased."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            _to_keyvault_name,
        )

        assert _to_keyvault_name("JWT_SECRET_KEY") == "jwt-secret-key"

    def test_already_lowercase(self):
        """Test that already-lowercase names are handled."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            _to_keyvault_name,
        )

        assert _to_keyvault_name("redis-url") == "redis-url"

    def test_no_underscores(self):
        """Test names without underscores."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            _to_keyvault_name,
        )

        assert _to_keyvault_name("password") == "password"


# ============================================================================
# SecretProviderFactory Tests
# ============================================================================


class TestSecretProviderFactory:
    """Tests for SecretProviderFactory (provider selection and construction)."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Reset provider factory to default before/after each test."""
        set_provider(None)
        yield
        set_provider(None)

    def test_factory_creates_env_provider_by_default(self):
        """Test that factory creates EnvSecretProvider when SECRET_PROVIDER=env."""
        with patch.dict(os.environ, {"SECRET_PROVIDER": "env"}):
            set_provider(None)
            provider = get_provider()
            assert isinstance(provider, EnvSecretProvider)

    def test_factory_creates_env_provider_when_unset(self):
        """Test that factory creates EnvSecretProvider when SECRET_PROVIDER is not set."""
        env = os.environ.copy()
        env.pop("SECRET_PROVIDER", None)
        with patch.dict(os.environ, env, clear=True):
            set_provider(None)

            import importlib

            import services.api.infrastructure.secret_provider_factory as factory_mod

            importlib.reload(factory_mod)
            factory_mod._provider = None

            provider = factory_mod.get_provider()
            assert isinstance(provider, EnvSecretProvider)

    def test_factory_creates_azure_provider(self):
        """Test that factory creates AzureKeyVaultSecretProvider when SECRET_PROVIDER=azure."""
        from services.api.infrastructure.azure_keyvault_secret_provider import (
            AzureKeyVaultSecretProvider,
        )

        with (
            patch.dict(
                os.environ,
                {
                    "SECRET_PROVIDER": "azure",
                    "AZURE_KEYVAULT_URL": "https://fxlab-prod.vault.azure.net",
                },
            ),
            patch(
                "services.api.infrastructure.azure_keyvault_secret_provider._AZURE_AVAILABLE",
                True,
            ),
            patch(
                "services.api.infrastructure.azure_keyvault_secret_provider.DefaultAzureCredential"
            ),
            patch("services.api.infrastructure.azure_keyvault_secret_provider.SecretClient"),
        ):
            import importlib

            import services.api.infrastructure.secret_provider_factory as factory_mod

            importlib.reload(factory_mod)
            factory_mod._provider = None

            provider = factory_mod.get_provider()
            assert isinstance(provider, AzureKeyVaultSecretProvider)

    def test_factory_azure_missing_url_raises_valueerror(self):
        """Test that factory raises ValueError when azure provider selected but URL missing."""
        env = os.environ.copy()
        env["SECRET_PROVIDER"] = "azure"
        env.pop("AZURE_KEYVAULT_URL", None)

        with patch.dict(os.environ, env, clear=True):
            import importlib

            import services.api.infrastructure.secret_provider_factory as factory_mod

            importlib.reload(factory_mod)
            factory_mod._provider = None

            with pytest.raises(ValueError, match="AZURE_KEYVAULT_URL"):
                factory_mod.get_provider()

    def test_factory_unknown_type_falls_back_to_env(self):
        """Test that unknown provider type falls back to EnvSecretProvider."""
        with patch.dict(os.environ, {"SECRET_PROVIDER": "unknown_provider"}):
            import importlib

            import services.api.infrastructure.secret_provider_factory as factory_mod

            importlib.reload(factory_mod)
            factory_mod._provider = None

            provider = factory_mod.get_provider()
            assert isinstance(provider, EnvSecretProvider)

    def test_set_provider_replaces_singleton(self):
        """Test that set_provider replaces the global singleton."""
        mock_provider = MagicMock(spec=SecretProviderInterface)
        set_provider(mock_provider)

        provider = get_provider()
        assert provider is mock_provider

    def test_set_provider_none_resets_singleton(self):
        """Test that set_provider(None) resets the singleton."""
        mock_provider = MagicMock(spec=SecretProviderInterface)
        set_provider(mock_provider)
        assert get_provider() is mock_provider

        set_provider(None)
        # Next call should create a new default provider
        provider = get_provider()
        assert isinstance(provider, EnvSecretProvider)
