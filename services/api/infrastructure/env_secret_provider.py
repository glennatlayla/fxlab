"""
Environment-variable-backed SecretProvider with rotation support.

Responsibilities:
- Read secret values from os.environ.
- Support runtime secret rotation via the _NEW suffix convention:
  1. Operator sets KEY_NEW=<new-value> in the environment (e.g. via K8s secret update).
  2. rotate_secret(KEY, new_value) validates KEY_NEW matches, then:
     - Stores KEY_OLD = current value (accessible during rotation window).
     - Stores KEY = new value (in-memory override, takes precedence over env).
  3. Both old and new values remain accessible during the rotation window.
- Provide metadata about known secret keys and their set/unset/rotation state.
- Report secrets approaching expiry via list_expiring(threshold_days).

Does NOT:
- Persist rotation state to disk (rotation state is per-process; a restart
  re-reads from env, which the operator has updated by then).
- Access external secret stores (Vault, AWS Secrets Manager).
- Manage TLS certificates or non-string secrets.

Dependencies:
- os.environ (stdlib).
- threading.Lock (stdlib) for concurrent rotation safety.
- SecretProviderInterface, SecretMetadata (libs.contracts.interfaces.secret_provider).

Error conditions:
- get_secret raises KeyError when the requested key has no value (env or rotated).
- rotate_secret raises KeyError when KEY_NEW is not set in the environment.
- rotate_secret raises ValueError when new_value does not match KEY_NEW env var.

Example:
    # Operator has set: JWT_SECRET_KEY=old-key, JWT_SECRET_KEY_NEW=new-key
    provider = EnvSecretProvider()
    provider.rotate_secret("JWT_SECRET_KEY", "new-key")
    assert provider.get_secret("JWT_SECRET_KEY") == "new-key"
    assert provider.get_secret("JWT_SECRET_KEY_OLD") == "old-key"
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone

import structlog

from libs.contracts.interfaces.secret_provider import (
    SecretMetadata,
    SecretProviderInterface,
)

logger = structlog.get_logger(__name__)

# Keys that EnvSecretProvider considers "known" for list_secrets metadata.
# Extend this tuple as the application adds new managed secrets.
_KNOWN_SECRET_KEYS: tuple[str, ...] = (
    "JWT_SECRET_KEY",
    "DATABASE_URL",
    "KEYCLOAK_ADMIN_CLIENT_SECRET",
    "REDIS_URL",
)


class EnvSecretProvider(SecretProviderInterface):
    """
    Reads secrets from os.environ with runtime rotation support.

    This is the default production provider for bootstrap environments
    where secrets are injected via container env vars, .env files, or
    orchestrator secret mounts (e.g. Docker secrets -> /run/secrets/*
    symlinked into env).

    Rotation workflow:
        1. Operator sets KEY_NEW=<new-value> in the environment.
        2. Application (or SecretRotationJob) calls rotate_secret(KEY, new_value).
        3. Provider swaps: current -> KEY_OLD, new -> KEY (in-memory).
        4. Both KEY and KEY_OLD are readable during the rotation window.
        5. Operator removes KEY_NEW and KEY_OLD from env on next deploy.

    Thread safety:
        All mutable state (_rotated_values, _old_values, _rotation_timestamps)
        is protected by _lock. Concurrent rotate_secret and get_secret calls
        are safe.

    Responsibilities:
    - Retrieve individual secrets from the process environment or rotation cache.
    - Report metadata (set/unset/last_rotated) for a predefined list of known keys.
    - Support zero-downtime rotation via _NEW suffix convention.
    - Report secrets approaching expiry via list_expiring().

    Does NOT:
    - Persist rotation state across process restarts.
    - Cache or transform secret values beyond rotation overrides.

    Example:
        provider = EnvSecretProvider()
        assert provider.get_secret("DATABASE_URL").startswith("postgresql://")
    """

    def __init__(self) -> None:
        """
        Initialise the provider with empty rotation state.

        The lock protects all mutable instance state for thread safety
        per CLAUDE.md §0 Rule 6 (no unprotected shared mutable state).
        """
        self._lock = threading.Lock()
        # In-memory overrides after rotation (KEY -> new_value)
        self._rotated_values: dict[str, str] = {}
        # Previous values preserved during rotation window (KEY -> old_value)
        self._old_values: dict[str, str] = {}
        # UTC timestamps of most recent rotation per key
        self._rotation_timestamps: dict[str, datetime] = {}

    def get_secret(self, key: str) -> str:
        """
        Retrieve a secret value, checking rotation cache before os.environ.

        Resolution order:
            1. _OLD suffix: if key ends with _OLD, return the preserved old value.
            2. Rotation cache: if key was rotated in-memory, return the new value.
            3. os.environ: fall back to the environment variable.

        Args:
            key: Environment variable name (e.g. "DATABASE_URL", "JWT_SECRET_KEY_OLD").

        Returns:
            The secret value as a string.

        Raises:
            KeyError: If the secret is not found in any source.

        Example:
            value = provider.get_secret("JWT_SECRET_KEY")
        """
        with self._lock:
            # Check for _OLD suffix — return preserved pre-rotation value
            if key.endswith("_OLD"):
                base_key = key[: -len("_OLD")]
                if base_key in self._old_values:
                    return self._old_values[base_key]
                # Fall through to env check

            # Check rotation cache (in-memory overrides)
            if key in self._rotated_values:
                return self._rotated_values[key]

        # Fall back to os.environ
        value = os.environ.get(key)
        if value is None:
            logger.warning(
                "secret.env.missing",
                key=key,
                component="EnvSecretProvider",
            )
            raise KeyError(key)
        return value

    def get_secret_or_default(self, key: str, default: str) -> str:
        """
        Retrieve a secret, returning *default* if absent from all sources.

        Args:
            key: Environment variable name.
            default: Fallback value when the variable is not set.

        Returns:
            The secret value, or *default*.

        Example:
            level = provider.get_secret_or_default("LOG_LEVEL", "INFO")
        """
        try:
            return self.get_secret(key)
        except KeyError:
            return default

    def rotate_secret(self, key: str, new_value: str) -> None:
        """
        Rotate a secret using the _NEW suffix convention.

        Workflow:
            1. Read KEY_NEW from os.environ — raises KeyError if missing.
            2. Verify new_value matches KEY_NEW — raises ValueError on mismatch.
            3. Swap: current value -> _old_values[KEY], new_value -> _rotated_values[KEY].
            4. Record rotation timestamp.
            5. Log the rotation event at INFO level.

        Both the old and new values remain accessible:
            - get_secret(KEY) returns new_value
            - get_secret(KEY_OLD) returns the previous value

        Args:
            key: Logical secret identifier (e.g. "JWT_SECRET_KEY").
            new_value: Expected new value (must match KEY_NEW env var).

        Raises:
            KeyError: If KEY_NEW is not set in the environment.
            ValueError: If new_value does not match KEY_NEW env var.

        Example:
            # With JWT_SECRET_KEY_NEW=new-key in env:
            provider.rotate_secret("JWT_SECRET_KEY", "new-key")
        """
        new_env_key = f"{key}_NEW"

        # Step 1: Read KEY_NEW from environment
        env_new_value = os.environ.get(new_env_key)
        if env_new_value is None:
            logger.warning(
                "secret.rotation.missing_new",
                key=key,
                new_env_key=new_env_key,
                component="EnvSecretProvider",
            )
            raise KeyError(
                f"{new_env_key} is not set in the environment. "
                f"Set {new_env_key}=<new-value> before calling rotate_secret."
            )

        # Step 2: Verify new_value matches the env var (safety check)
        if new_value != env_new_value:
            raise ValueError(
                f"Provided new_value does not match {new_env_key} environment variable. "
                "This is a safety check to prevent accidental mis-rotation."
            )

        with self._lock:
            # Step 3: Preserve current value as old
            try:
                current_value = self._rotated_values.get(key) or os.environ.get(key)
                if current_value is not None:
                    self._old_values[key] = current_value
            except Exception:
                # If we can't read the current value, proceed anyway —
                # the new value is more important than preserving the old.
                pass

            # Step 4: Store the new value in rotation cache
            self._rotated_values[key] = new_value

            # Step 5: Record timestamp
            self._rotation_timestamps[key] = datetime.now(timezone.utc)

        # Step 6: Log (outside lock to avoid holding lock during I/O)
        logger.info(
            "secret.rotated",
            key=key,
            component="EnvSecretProvider",
            operation="rotate_secret",
        )

    def list_secrets(self) -> list[SecretMetadata]:
        """
        Return metadata for all known secret keys.

        Each key in _KNOWN_SECRET_KEYS is checked against rotation cache
        and os.environ to determine its current state.

        Returns:
            List of SecretMetadata, one per known key.

        Example:
            for meta in provider.list_secrets():
                print(f"{meta.key}: set={meta.is_set}, rotated={meta.last_rotated}")
        """
        result: list[SecretMetadata] = []
        with self._lock:
            for key in _KNOWN_SECRET_KEYS:
                is_set = key in self._rotated_values or key in os.environ
                result.append(
                    SecretMetadata(
                        key=key,
                        source="environment",
                        is_set=is_set,
                        last_rotated=self._rotation_timestamps.get(key),
                        description="",
                    )
                )
        return result

    def list_expiring(self, threshold_days: int) -> list[SecretMetadata]:
        """
        Return metadata for secrets that are approaching expiry.

        A secret is considered "expiring" if:
            - It is currently set (has a value), AND
            - It has never been rotated, OR
            - It was last rotated more than threshold_days ago.

        Args:
            threshold_days: Number of days since last rotation to consider
                a secret as approaching expiry.

        Returns:
            List of SecretMetadata for secrets that need rotation attention.

        Example:
            expiring = provider.list_expiring(threshold_days=90)
            for meta in expiring:
                print(f"EXPIRING: {meta.key}, last_rotated={meta.last_rotated}")
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        result: list[SecretMetadata] = []
        with self._lock:
            for key in _KNOWN_SECRET_KEYS:
                is_set = key in self._rotated_values or key in os.environ
                if not is_set:
                    continue  # Unset secrets are not "expiring"

                last_rotated = self._rotation_timestamps.get(key)
                if last_rotated is None or last_rotated < cutoff:
                    result.append(
                        SecretMetadata(
                            key=key,
                            source="environment",
                            is_set=True,
                            last_rotated=last_rotated,
                            description="",
                        )
                    )
        return result
