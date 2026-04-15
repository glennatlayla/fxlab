"""
Azure Key Vault-backed SecretProvider with caching and DefaultAzureCredential.

Responsibilities:
- Retrieve secrets from Azure Key Vault via the azure-keyvault-secrets SDK.
- Authenticate via DefaultAzureCredential (managed identity, CLI, env vars).
- Cache secrets in memory with configurable TTL to minimise API calls.
- Log all access events at DEBUG level for audit compliance.
- Map logical key names to Key Vault-compatible names (underscores → hyphens).

Does NOT:
- Rotate secrets (Azure Key Vault handles rotation policies natively).
- Store secrets locally beyond process memory.
- Manage Key Vault access policies (operator/admin responsibility).
- Support certificate retrieval (secrets only).

Dependencies:
- azure-identity (DefaultAzureCredential for auth).
- azure-keyvault-secrets (SecretClient for secret access).
- structlog (logging).
- SecretProviderInterface (abstract base).
- threading (stdlib, for thread-safe cache access).

Error conditions:
- get_secret raises KeyError if secret not found in Key Vault.
- ImportError if azure-identity or azure-keyvault-secrets not installed.
- Azure SDK errors (404 ResourceNotFoundError, auth failures) are logged and
  converted to KeyError for consistent interface behaviour.
- rotate_secret raises NotImplementedError (use Azure Key Vault rotation).

Example:
    provider = AzureKeyVaultSecretProvider(
        vault_url="https://fxlab-prod.vault.azure.net",
        prefix="fxlab-",
    )
    db_url = provider.get_secret("DATABASE_URL")
    # Fetches secret named "fxlab-DATABASE-URL" from Azure Key Vault
    # (underscores converted to hyphens per Key Vault naming rules)
    # Caches result for 5 minutes (default TTL)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import structlog

from libs.contracts.interfaces.secret_provider import (
    SecretMetadata,
    SecretProviderInterface,
)

logger = structlog.get_logger(__name__)

# Conditional imports: azure SDK is optional
try:
    from azure.core.exceptions import (
        ClientAuthenticationError as AzureAuthError,
    )
    from azure.core.exceptions import (
        HttpResponseError as AzureHttpResponseError,
    )
    from azure.core.exceptions import (
        ResourceNotFoundError as AzureResourceNotFoundError,
    )
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    _AZURE_AVAILABLE = True
except ImportError:
    _AZURE_AVAILABLE = False
    DefaultAzureCredential = None  # type: ignore[assignment,misc]
    SecretClient = None  # type: ignore[assignment,misc]
    AzureResourceNotFoundError = Exception  # type: ignore[assignment,misc]
    AzureHttpResponseError = Exception  # type: ignore[assignment,misc]
    AzureAuthError = Exception  # type: ignore[assignment,misc]


def _to_keyvault_name(key: str) -> str:
    """
    Convert a logical secret key to Azure Key Vault-compatible name.

    Azure Key Vault secret names only allow alphanumeric characters and
    hyphens. This function converts underscores to hyphens and lowercases
    the result for consistency.

    Args:
        key: Logical secret identifier (e.g., "DATABASE_URL").

    Returns:
        Key Vault-compatible name (e.g., "database-url").

    Example:
        _to_keyvault_name("JWT_SECRET_KEY") == "jwt-secret-key"
        _to_keyvault_name("REDIS_URL") == "redis-url"
    """
    return key.replace("_", "-").lower()


class AzureKeyVaultSecretProvider(SecretProviderInterface):
    """
    Retrieve secrets from Azure Key Vault with in-memory caching.

    Architecture:
        - Uses azure-keyvault-secrets SecretClient to fetch secrets.
        - Authenticates via DefaultAzureCredential (supports managed identity,
          Azure CLI, environment variables, and workload identity).
        - Caches each secret in memory (timestamp + value) with configurable TTL.
        - Converts logical key names to Key Vault-compatible format
          (underscores → hyphens, lowercased).
        - Thread-safe cache access via _lock.

    Responsibilities:
    - Fetch secrets by key from Azure Key Vault.
    - Cache secrets in memory with TTL to minimise API calls.
    - Map logical names to Key Vault naming convention.
    - Log access events for audit compliance.

    Does NOT:
    - Rotate secrets (handled by Azure Key Vault rotation policies).
    - Store secrets locally beyond process memory.
    - Manage Key Vault access policies or RBAC (admin responsibility).

    Dependencies:
    - azure-identity (DefaultAzureCredential, conditionally imported).
    - azure-keyvault-secrets (SecretClient, conditionally imported).
    - threading.Lock (stdlib) for cache synchronisation.

    Error conditions:
    - get_secret raises KeyError when secret not found.
    - ImportError if azure SDK packages are not installed.
    - Azure auth errors are logged and converted to KeyError.

    Example:
        provider = AzureKeyVaultSecretProvider(
            vault_url="https://fxlab-prod.vault.azure.net",
            prefix="fxlab-",
        )
        db_url = provider.get_secret("DATABASE_URL")
    """

    def __init__(
        self,
        *,
        vault_url: str,
        prefix: str = "fxlab-",
        cache_ttl_seconds: int = 300,
        credential: object | None = None,
    ) -> None:
        """
        Initialise Azure Key Vault provider with DefaultAzureCredential.

        Args:
            vault_url: The Key Vault URL (e.g., "https://fxlab-prod.vault.azure.net").
                Must be a valid Azure Key Vault endpoint. Required.
            prefix: Prefix prepended to all secret names when fetching from
                Key Vault (e.g., prefix="fxlab-" for key="DATABASE_URL" fetches
                secret named "fxlab-database-url"). Default: "fxlab-".
            cache_ttl_seconds: How long (in seconds) to cache secrets before
                refetching from Key Vault. Default: 300 (5 minutes).
            credential: Optional Azure credential object. If None, uses
                DefaultAzureCredential (recommended for production — supports
                managed identity, CLI, env vars automatically). Pass a custom
                credential for testing or non-standard auth flows.

        Raises:
            ImportError: If azure-identity or azure-keyvault-secrets not installed.
            ValueError: If vault_url is empty or None.

        Example:
            # Production (uses managed identity or Azure CLI automatically):
            provider = AzureKeyVaultSecretProvider(
                vault_url="https://fxlab-prod.vault.azure.net",
            )

            # Custom credential:
            from azure.identity import ManagedIdentityCredential
            provider = AzureKeyVaultSecretProvider(
                vault_url="https://fxlab-prod.vault.azure.net",
                credential=ManagedIdentityCredential(),
            )
        """
        if not _AZURE_AVAILABLE:
            raise ImportError(
                "azure-identity and azure-keyvault-secrets are required for "
                "AzureKeyVaultSecretProvider. Install them with:\n"
                "  pip install azure-identity azure-keyvault-secrets"
            )

        if not vault_url:
            raise ValueError("vault_url is required for AzureKeyVaultSecretProvider")

        # Normalise URL (remove trailing slash)
        self._vault_url = vault_url.rstrip("/")
        self._prefix = prefix
        self._cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.Lock()
        # Cache format: keyvault_name -> (value, timestamp)
        self._cache: dict[str, tuple[str, float]] = {}

        # Create credential and client
        self._credential = credential or DefaultAzureCredential()
        self._client = SecretClient(
            vault_url=self._vault_url,
            credential=self._credential,
        )

        logger.debug(
            "azure.keyvault.secret_provider.initialized",
            vault_url=self._vault_url,
            prefix=prefix,
            cache_ttl_seconds=cache_ttl_seconds,
            component="AzureKeyVaultSecretProvider",
        )

    def _resolve_keyvault_name(self, key: str) -> str:
        """
        Build the full Key Vault secret name from a logical key.

        Applies the prefix and converts to Key Vault naming convention
        (underscores → hyphens, lowercased).

        Args:
            key: Logical secret identifier (e.g., "DATABASE_URL").

        Returns:
            Full Key Vault secret name (e.g., "fxlab-database-url").

        Example:
            self._resolve_keyvault_name("JWT_SECRET_KEY")
            # Returns "fxlab-jwt-secret-key"
        """
        return f"{self._prefix}{_to_keyvault_name(key)}"

    def get_secret(self, key: str) -> str:
        """
        Retrieve a secret from Azure Key Vault with caching.

        Resolution order:
            1. Check in-memory cache (if not expired).
            2. Fetch from Azure Key Vault.
            3. Cache the result.
            4. Return the secret value.

        Key Vault name resolution: the logical key is prefixed and converted
        to Key Vault format (underscores → hyphens, lowercased). For example,
        key="DATABASE_URL" with prefix="fxlab-" fetches "fxlab-database-url".

        Args:
            key: Logical secret identifier (e.g., "DATABASE_URL", "JWT_SECRET_KEY").

        Returns:
            The secret value as a string.

        Raises:
            KeyError: If the secret is not found in Key Vault, or if the
                secret exists but has no value (disabled or expired version).

        Example:
            db_url = provider.get_secret("DATABASE_URL")
            # Fetches "fxlab-database-url" from Azure Key Vault
        """
        kv_name = self._resolve_keyvault_name(key)

        with self._lock:
            # Check cache first
            if kv_name in self._cache:
                cached_value, cached_time = self._cache[kv_name]
                age_seconds = datetime.now(timezone.utc).timestamp() - cached_time
                if age_seconds < self._cache_ttl_seconds:
                    logger.debug(
                        "azure.keyvault.secret.cache_hit",
                        key=key,
                        kv_name=kv_name,
                        age_seconds=round(age_seconds, 1),
                        component="AzureKeyVaultSecretProvider",
                    )
                    return cached_value

        # Cache miss or expired: fetch from Key Vault
        try:
            logger.debug(
                "azure.keyvault.secret.fetching",
                key=key,
                kv_name=kv_name,
                component="AzureKeyVaultSecretProvider",
            )

            secret_bundle = self._client.get_secret(kv_name)

            if secret_bundle.value is None:
                logger.warning(
                    "azure.keyvault.secret.empty_value",
                    key=key,
                    kv_name=kv_name,
                    component="AzureKeyVaultSecretProvider",
                )
                raise KeyError(key)

            result_value: str = secret_bundle.value

            # Cache the result
            with self._lock:
                self._cache[kv_name] = (
                    result_value,
                    datetime.now(timezone.utc).timestamp(),
                )

            logger.debug(
                "azure.keyvault.secret.fetched",
                key=key,
                kv_name=kv_name,
                component="AzureKeyVaultSecretProvider",
            )
            return result_value

        except AzureResourceNotFoundError:
            logger.warning(
                "azure.keyvault.secret.not_found",
                key=key,
                kv_name=kv_name,
                component="AzureKeyVaultSecretProvider",
            )
            raise KeyError(key)

        except AzureAuthError as e:
            logger.error(
                "azure.keyvault.secret.auth_failure",
                key=key,
                kv_name=kv_name,
                error=str(e),
                component="AzureKeyVaultSecretProvider",
                exc_info=True,
            )
            raise KeyError(key) from e

        except AzureHttpResponseError as e:
            logger.warning(
                "azure.keyvault.secret.http_error",
                key=key,
                kv_name=kv_name,
                status_code=e.status_code,
                component="AzureKeyVaultSecretProvider",
            )
            raise KeyError(key) from e

        except Exception as e:
            logger.error(
                "azure.keyvault.secret.unexpected_error",
                key=key,
                kv_name=kv_name,
                component="AzureKeyVaultSecretProvider",
                exc_info=True,
            )
            raise KeyError(key) from e

    def get_secret_or_default(self, key: str, default: str) -> str:
        """
        Retrieve a secret, returning *default* if not found.

        Args:
            key: Logical secret identifier.
            default: Fallback value when the secret is not found.

        Returns:
            The secret value, or *default*.

        Example:
            level = provider.get_secret_or_default("LOG_LEVEL", "INFO")
        """
        try:
            return self.get_secret(key)
        except KeyError:
            logger.debug(
                "azure.keyvault.secret.default_used",
                key=key,
                component="AzureKeyVaultSecretProvider",
            )
            return default

    def rotate_secret(self, key: str, new_value: str) -> None:
        """
        Rotate a secret (not implemented; use Azure Key Vault rotation).

        Azure Key Vault provides built-in secret rotation via:
        - Azure Key Vault rotation policies (auto-rotation)
        - Event Grid integration for rotation notifications
        - Azure Functions for custom rotation logic

        This provider does not support rotation via the SecretProviderInterface.

        Args:
            key: Logical secret identifier.
            new_value: The replacement value (unused).

        Raises:
            NotImplementedError: Always. Use Azure Key Vault rotation policies.

        Example:
            # Use Azure Key Vault rotation policies instead
            # See: https://learn.microsoft.com/en-us/azure/key-vault/secrets/tutorial-rotation
        """
        raise NotImplementedError(
            "AzureKeyVaultSecretProvider does not support rotate_secret. "
            "Use Azure Key Vault rotation policies instead. "
            "See: https://learn.microsoft.com/en-us/azure/key-vault/secrets/tutorial-rotation"
        )

    def list_secrets(self) -> list[SecretMetadata]:
        """
        Return metadata for secrets in the Key Vault matching the prefix.

        Lists all secrets in the vault (name and metadata only, not values)
        and returns those whose names start with the configured prefix.

        Returns:
            List of SecretMetadata for matching secrets.

        Example:
            for meta in provider.list_secrets():
                print(f"{meta.key}: set={meta.is_set}")
        """
        result: list[SecretMetadata] = []
        try:
            for secret_properties in self._client.list_properties_of_secrets():
                name = secret_properties.name or ""
                if not name.startswith(self._prefix):
                    continue

                # Convert Key Vault name back to logical key
                logical_suffix = name[len(self._prefix) :]
                logical_key = logical_suffix.replace("-", "_").upper()

                result.append(
                    SecretMetadata(
                        key=logical_key,
                        source="azure-keyvault",
                        is_set=secret_properties.enabled is True,
                        last_rotated=secret_properties.updated_on,
                        description=secret_properties.content_type or "",
                    )
                )
        except Exception:
            logger.warning(
                "azure.keyvault.list_secrets.failed",
                component="AzureKeyVaultSecretProvider",
                exc_info=True,
            )
        return result

    def close(self) -> None:
        """
        Close the underlying Azure SDK clients.

        Should be called during application shutdown to release resources.
        Safe to call multiple times.

        Example:
            provider.close()
        """
        try:
            if hasattr(self, "_client"):
                self._client.close()
            if hasattr(self, "_credential") and hasattr(self._credential, "close"):
                self._credential.close()
        except Exception:
            pass

    def __del__(self) -> None:
        """Clean up Azure SDK clients on garbage collection."""
        self.close()
