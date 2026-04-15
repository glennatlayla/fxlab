"""
In-memory SecretProvider implementation for testing.

Responsibilities:
- Store secrets in a plain dict for fast, isolated unit tests.
- Support secret rotation with timestamp tracking.
- Provide introspection helpers for test assertions.

Does NOT:
- Persist secrets beyond the lifetime of the object.
- Enforce access control or audit logging.

Dependencies:
- SecretProviderInterface, SecretMetadata (libs.contracts.interfaces.secret_provider).

Example:
    provider = MockSecretProvider({"DB_URL": "sqlite:///:memory:"})
    assert provider.get_secret("DB_URL") == "sqlite:///:memory:"
    provider.rotate_secret("DB_URL", "postgresql://prod")
    assert provider.get_rotation_count() == 1
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.interfaces.secret_provider import (
    SecretMetadata,
    SecretProviderInterface,
)


class MockSecretProvider(SecretProviderInterface):
    """
    In-memory secret provider for unit and integration tests.

    Responsibilities:
    - Store and retrieve secrets from a plain dict.
    - Track rotation history for test assertions.

    Does NOT:
    - Validate secret strength or format.
    - Enforce any access control.

    Example:
        provider = MockSecretProvider({"JWT_SECRET_KEY": "test-key"})
        assert provider.get_secret("JWT_SECRET_KEY") == "test-key"
        provider.rotate_secret("JWT_SECRET_KEY", "rotated-key")
        assert provider.get_rotation_count() == 1
    """

    def __init__(self, initial_secrets: dict[str, str] | None = None) -> None:
        """
        Initialise with an optional dict of pre-populated secrets.

        Args:
            initial_secrets: Key-value pairs to seed the store. Defaults to empty.
        """
        self._store: dict[str, str] = dict(initial_secrets or {})
        self._rotation_timestamps: dict[str, datetime] = {}
        self._rotation_count: int = 0

    def get_secret(self, key: str) -> str:
        """
        Retrieve a secret by key.

        Args:
            key: Logical secret identifier.

        Returns:
            The secret value.

        Raises:
            KeyError: If the key is not in the store.

        Example:
            value = provider.get_secret("DB_URL")
        """
        if key not in self._store:
            raise KeyError(key)
        return self._store[key]

    def get_secret_or_default(self, key: str, default: str) -> str:
        """
        Retrieve a secret, falling back to *default* if absent.

        Args:
            key: Logical secret identifier.
            default: Fallback value.

        Returns:
            The stored value, or *default*.

        Example:
            level = provider.get_secret_or_default("LOG_LEVEL", "INFO")
        """
        return self._store.get(key, default)

    def rotate_secret(self, key: str, new_value: str) -> None:
        """
        Replace (or create) a secret value and record the rotation.

        Args:
            key: Logical secret identifier.
            new_value: Replacement value.

        Example:
            provider.rotate_secret("JWT_SECRET_KEY", "new-key-value")
        """
        self._store[key] = new_value
        self._rotation_timestamps[key] = datetime.now(timezone.utc)
        self._rotation_count += 1

    def list_secrets(self) -> list[SecretMetadata]:
        """
        Return metadata for every secret currently in the store.

        Returns:
            List of SecretMetadata, one per stored key.

        Example:
            for meta in provider.list_secrets():
                print(f"{meta.key}: rotated={meta.last_rotated}")
        """
        result: list[SecretMetadata] = []
        for key, _value in self._store.items():
            result.append(
                SecretMetadata(
                    key=key,
                    source="memory",
                    is_set=True,
                    last_rotated=self._rotation_timestamps.get(key),
                    description="",
                )
            )
        return result

    # ------------------------------------------------------------------
    # Introspection helpers (test-only)
    # ------------------------------------------------------------------

    def get_rotation_count(self) -> int:
        """
        Return the total number of rotate_secret() calls made.

        Example:
            assert provider.get_rotation_count() == 2
        """
        return self._rotation_count

    def get_all(self) -> dict[str, str]:
        """
        Return a shallow copy of the entire secret store.

        Example:
            assert "DB_URL" in provider.get_all()
        """
        return dict(self._store)

    def clear(self) -> None:
        """
        Remove all secrets and reset rotation tracking.

        Example:
            provider.clear()
            assert provider.get_rotation_count() == 0
        """
        self._store.clear()
        self._rotation_timestamps.clear()
        self._rotation_count = 0
