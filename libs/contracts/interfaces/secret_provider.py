"""
SecretProvider interface and SecretMetadata contract.

Responsibilities:
- Define the abstract contract for secret retrieval, rotation, and listing.
- Define the SecretMetadata value object describing a secret's state.

Does NOT:
- Contain any concrete implementation (see EnvSecretProvider, MockSecretProvider).
- Enforce access control or audit logging (caller's responsibility).

Dependencies:
- None (pure domain contract).

Example:
    class VaultSecretProvider(SecretProviderInterface):
        def get_secret(self, key: str) -> str:
            return vault_client.read(f"secret/data/{key}")["data"]["value"]
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import Field

from libs.contracts.base import FXLabBaseModel


class SecretMetadata(FXLabBaseModel):
    """
    Immutable value object describing the state of a managed secret.

    Attributes:
        key: The secret's logical identifier (e.g. "JWT_SECRET_KEY").
        source: Origin label (e.g. "environment", "vault", "memory").
        is_set: Whether the secret currently has a value.
        last_rotated: UTC timestamp of the most recent rotation, or None.
        description: Human-readable description of the secret's purpose.

    Example:
        meta = SecretMetadata(
            key="DATABASE_URL",
            source="environment",
            is_set=True,
            description="PostgreSQL connection string",
        )
    """

    key: str = Field(..., description="Logical secret identifier")
    source: str = Field(..., description="Origin label (environment, vault, memory)")
    is_set: bool = Field(..., description="Whether the secret currently has a value")
    last_rotated: datetime | None = Field(
        default=None,
        description="UTC timestamp of most recent rotation",
    )
    description: str = Field(
        default="",
        description="Human-readable description of the secret's purpose",
    )


class SecretProviderInterface(ABC):
    """
    Abstract contract for centralised secret access.

    Responsibilities:
    - Retrieve secrets by key.
    - Rotate (update) secrets by key.
    - List metadata for all managed secrets.

    Does NOT:
    - Enforce who can read or rotate secrets (caller enforces RBAC).
    - Persist audit events (caller or decorator responsibility).

    Implementations:
    - EnvSecretProvider: reads from os.environ (production bootstrap).
    - MockSecretProvider: in-memory dict (testing).
    - (Future) VaultSecretProvider: HashiCorp Vault or AWS Secrets Manager.

    Example:
        provider: SecretProviderInterface = EnvSecretProvider()
        db_url = provider.get_secret("DATABASE_URL")
    """

    @abstractmethod
    def get_secret(self, key: str) -> str:
        """
        Retrieve a secret value by key.

        Args:
            key: Logical secret identifier (e.g. "JWT_SECRET_KEY").

        Returns:
            The secret value as a string.

        Raises:
            KeyError: If the secret is not found or not set.

        Example:
            value = provider.get_secret("DATABASE_URL")
        """

    @abstractmethod
    def get_secret_or_default(self, key: str, default: str) -> str:
        """
        Retrieve a secret value, falling back to a default if not found.

        Args:
            key: Logical secret identifier.
            default: Value to return if the secret is not set.

        Returns:
            The secret value, or *default* if absent.

        Example:
            log_level = provider.get_secret_or_default("LOG_LEVEL", "INFO")
        """

    @abstractmethod
    def rotate_secret(self, key: str, new_value: str) -> None:
        """
        Replace the current value of a secret.

        Args:
            key: Logical secret identifier.
            new_value: The replacement value.

        Raises:
            NotImplementedError: If the provider does not support rotation.

        Example:
            provider.rotate_secret("JWT_SECRET_KEY", new_key)
        """

    @abstractmethod
    def list_secrets(self) -> list[SecretMetadata]:
        """
        Return metadata for all secrets managed by this provider.

        Returns:
            List of SecretMetadata value objects.

        Example:
            for meta in provider.list_secrets():
                print(f"{meta.key}: set={meta.is_set}")
        """
