"""
SecretProvider factory — module-level singleton with configurable backends.

Responsibilities:
- Create and return the process-wide SecretProviderInterface instance.
- Support multiple backends via SECRET_PROVIDER environment variable.
- In production: returns EnvSecretProvider (default) or AzureKeyVaultSecretProvider.
- In tests: returns injected provider via set_provider().

Supported providers:
- "env": EnvSecretProvider (reads from os.environ, default).
- "azure": AzureKeyVaultSecretProvider (reads from Azure Key Vault).

Does NOT:
- Decide which provider to use based on complex logic (simple env-based).
- Manage provider lifecycle beyond singleton creation.
- Support dynamic provider switching after initial creation (static per process).

Dependencies:
- EnvSecretProvider (default implementation).
- AzureKeyVaultSecretProvider (Azure Key Vault implementation, optional).
- SecretProviderInterface (contract).
- os (stdlib, for environment variables).
- structlog (logging).

Configuration (environment variables):
- SECRET_PROVIDER: "env" (default) or "azure".
- AZURE_KEYVAULT_URL: Key Vault URL (required for azure provider).
- SECRET_PREFIX: Key prefix for secrets (default: fxlab-).

Example:
    from services.api.infrastructure.secret_provider_factory import get_provider
    db_url = get_provider().get_secret("DATABASE_URL")
"""

from __future__ import annotations

import os

import structlog

from libs.contracts.interfaces.secret_provider import SecretProviderInterface
from services.api.infrastructure.env_secret_provider import EnvSecretProvider

logger = structlog.get_logger(__name__)

_provider: SecretProviderInterface | None = None


def _create_azure_provider() -> SecretProviderInterface:
    """
    Create and return an AzureKeyVaultSecretProvider instance.

    Reads configuration from environment variables:
    - AZURE_KEYVAULT_URL: Key Vault URL (required, e.g. https://fxlab-prod.vault.azure.net)
    - SECRET_PREFIX: Key prefix (default: fxlab-)

    Authentication via DefaultAzureCredential (supports managed identity,
    Azure CLI, environment variables, workload identity — in that order).

    Returns:
        AzureKeyVaultSecretProvider instance.

    Raises:
        ImportError: If azure-identity or azure-keyvault-secrets not installed.
        ValueError: If AZURE_KEYVAULT_URL is not set.
    """
    from services.api.infrastructure.azure_keyvault_secret_provider import (
        AzureKeyVaultSecretProvider,
    )

    vault_url = os.environ.get("AZURE_KEYVAULT_URL")
    if not vault_url:
        raise ValueError(
            "AZURE_KEYVAULT_URL environment variable is required for azure "
            "secret provider. Set it to your Key Vault URL, e.g. "
            "https://fxlab-prod.vault.azure.net"
        )

    prefix = os.environ.get("SECRET_PREFIX", "fxlab-")

    logger.info(
        "secret_provider.azure.creating",
        vault_url=vault_url,
        prefix=prefix,
        component="SecretProviderFactory",
    )

    return AzureKeyVaultSecretProvider(vault_url=vault_url, prefix=prefix)


def get_provider() -> SecretProviderInterface:
    """
    Return the process-wide SecretProvider singleton.

    Provider selection based on SECRET_PROVIDER environment variable:
    - "env" (default): EnvSecretProvider (reads os.environ).
    - "azure": AzureKeyVaultSecretProvider (reads Azure Key Vault).

    Creates the provider on first call; subsequent calls return the
    same instance. Tests can swap the instance via set_provider()
    before importing application code.

    Returns:
        The active SecretProviderInterface instance.

    Raises:
        ValueError: If azure provider is selected but AZURE_KEYVAULT_URL is not set.
        ImportError: If azure provider is selected but azure SDK packages not installed.

    Example:
        provider = get_provider()
        jwt_key = provider.get_secret("JWT_SECRET_KEY")
    """
    global _provider
    if _provider is None:
        provider_type = os.environ.get("SECRET_PROVIDER", "env").lower()

        if provider_type == "azure":
            _provider = _create_azure_provider()
        elif provider_type == "env":
            _provider = EnvSecretProvider()
        else:
            logger.warning(
                "secret_provider.unknown_type",
                provider_type=provider_type,
                defaulting_to="env",
                component="SecretProviderFactory",
            )
            _provider = EnvSecretProvider()

    return _provider


def set_provider(provider: SecretProviderInterface | None) -> None:
    """
    Replace the global SecretProvider (test support only).

    This function is intended for testing only. Calling it after
    application startup may lead to inconsistent behaviour since
    some components may have already cached references to the
    original provider.

    Args:
        provider: New provider instance, or None to reset to default.

    Example:
        from tests.mocks import MockSecretProvider
        set_provider(MockSecretProvider({"KEY": "val"}))
    """
    global _provider
    _provider = provider
    if provider is not None:
        logger.debug(
            "secret_provider.set",
            provider_type=type(provider).__name__,
            component="SecretProviderFactory",
        )
