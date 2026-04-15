"""
Background job for automated secret rotation via the _NEW suffix convention.

Responsibilities:
- Periodically scan os.environ for known secret keys with _NEW suffixes.
- When a _NEW suffix is found, call EnvSecretProvider.rotate_secret()
  to execute the rotation (swap current -> old, new -> current).
- Log all rotation events at INFO level and failures at ERROR level.
- Continue processing remaining keys if an individual rotation fails.

Does NOT:
- Generate or create new secret values (operator provides via env).
- Remove _NEW env vars after rotation (operator's responsibility on next deploy).
- Persist rotation history to durable storage (in-memory per process lifecycle).
- Access external secret stores (Vault, AWS Secrets Manager).

Dependencies:
- EnvSecretProvider (injected): the secret provider to rotate secrets on.
- threading (stdlib): background daemon thread for periodic checks.
- os.environ (stdlib): scanned for _NEW suffixed variables.

Error conditions:
- Individual rotation failures are logged and skipped (other keys still rotate).
- start() is idempotent — calling it when already running is a no-op.
- stop() is idempotent — calling it when not running is a no-op.

Example:
    provider = EnvSecretProvider()
    job = SecretRotationJob(provider=provider, check_interval_seconds=300)
    job.start()   # Begin periodic checks
    # ... application runs ...
    job.stop()    # Graceful shutdown
"""

from __future__ import annotations

import os
import threading

import structlog

from services.api.infrastructure.env_secret_provider import (
    _KNOWN_SECRET_KEYS,
    EnvSecretProvider,
)

logger = structlog.get_logger(__name__)


class SecretRotationJob:
    """
    Daemon thread that periodically checks for _NEW env vars and rotates.

    The job scans _KNOWN_SECRET_KEYS for corresponding KEY_NEW environment
    variables. When found, it calls provider.rotate_secret(KEY, new_value)
    to execute the zero-downtime rotation.

    Thread safety:
        Internal state (_running, _stop_event, _thread) is protected by
        _lock. The EnvSecretProvider itself is thread-safe.

    Responsibilities:
    - Periodic scanning for _NEW suffixed env vars on known keys.
    - Triggering rotation on the injected provider.
    - Logging rotation successes and failures.

    Does NOT:
    - Own secret state (delegated to EnvSecretProvider).
    - Retry failed rotations (operator should fix the env and let next cycle handle it).

    Example:
        job = SecretRotationJob(provider=provider, check_interval_seconds=60)
        job.start()
        rotated = job.check_and_rotate()  # Manual trigger
        job.stop()
    """

    def __init__(
        self,
        provider: EnvSecretProvider,
        check_interval_seconds: float = 300.0,
    ) -> None:
        """
        Initialise the rotation job.

        Args:
            provider: The EnvSecretProvider instance to rotate secrets on.
            check_interval_seconds: How often (in seconds) to scan for _NEW
                env vars. Default: 300 (5 minutes).

        Example:
            job = SecretRotationJob(provider=provider, check_interval_seconds=60)
        """
        self._provider = provider
        self._check_interval = check_interval_seconds
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """
        Whether the background rotation thread is currently active.

        Returns:
            True if the background thread is running, False otherwise.

        Example:
            assert job.is_running is False
            job.start()
            assert job.is_running is True
        """
        with self._lock:
            return self._running

    def check_and_rotate(self) -> list[str]:
        """
        Scan for _NEW env vars on known keys and rotate any found.

        This is the core rotation logic, callable both from the background
        thread and manually (e.g. from an admin endpoint or startup hook).

        For each key in _KNOWN_SECRET_KEYS:
            1. Check if KEY_NEW exists in os.environ.
            2. If yes, call provider.rotate_secret(KEY, env_new_value).
            3. Log success at INFO, failure at ERROR.
            4. Continue to next key regardless of individual failures.

        Returns:
            List of key names that were successfully rotated.

        Example:
            rotated = job.check_and_rotate()
            # rotated == ["JWT_SECRET_KEY"] if JWT_SECRET_KEY_NEW was in env
        """
        rotated_keys: list[str] = []

        for key in _KNOWN_SECRET_KEYS:
            new_env_key = f"{key}_NEW"
            new_value = os.environ.get(new_env_key)
            if new_value is None:
                continue

            logger.info(
                "secret.rotation.detected",
                key=key,
                new_env_key=new_env_key,
                component="SecretRotationJob",
                operation="check_and_rotate",
            )

            try:
                self._provider.rotate_secret(key, new_value)
                rotated_keys.append(key)
                logger.info(
                    "secret.rotation.completed",
                    key=key,
                    component="SecretRotationJob",
                    operation="check_and_rotate",
                )
            except Exception:
                logger.error(
                    "secret.rotation.failed",
                    key=key,
                    component="SecretRotationJob",
                    operation="check_and_rotate",
                    exc_info=True,
                )

        if rotated_keys:
            logger.info(
                "secret.rotation.cycle_complete",
                rotated_count=len(rotated_keys),
                rotated_keys=rotated_keys,
                component="SecretRotationJob",
                operation="check_and_rotate",
            )

        return rotated_keys

    def start(self) -> None:
        """
        Start the background rotation check thread.

        Idempotent — calling start() when already running is a no-op.
        The thread is a daemon thread, so it does not prevent process exit.

        Example:
            job.start()
            assert job.is_running is True
        """
        with self._lock:
            if self._running:
                logger.warning(
                    "secret.rotation.already_running",
                    component="SecretRotationJob",
                    operation="start",
                )
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="secret-rotation-job",
                daemon=True,
            )
            self._running = True
            self._thread.start()

        logger.info(
            "secret.rotation.job_started",
            check_interval_seconds=self._check_interval,
            component="SecretRotationJob",
            operation="start",
        )

    def stop(self) -> None:
        """
        Stop the background rotation check thread.

        Idempotent — calling stop() when not running is a no-op.
        Blocks until the background thread terminates (up to check_interval).

        Example:
            job.stop()
            assert job.is_running is False
        """
        with self._lock:
            if not self._running:
                return
            self._stop_event.set()
            thread = self._thread

        if thread is not None:
            # Wait up to 2x check interval for the thread to finish
            thread.join(timeout=self._check_interval * 2)

        with self._lock:
            self._running = False
            self._thread = None

        logger.info(
            "secret.rotation.job_stopped",
            component="SecretRotationJob",
            operation="stop",
        )

    def _run_loop(self) -> None:
        """
        Internal loop: check for rotations, then sleep until next interval.

        Runs until _stop_event is set. Uses Event.wait() for interruptible sleep.
        """
        logger.debug(
            "secret.rotation.loop_started",
            component="SecretRotationJob",
            operation="_run_loop",
        )

        while not self._stop_event.is_set():
            try:
                self.check_and_rotate()
            except Exception:
                logger.error(
                    "secret.rotation.loop_error",
                    component="SecretRotationJob",
                    operation="_run_loop",
                    exc_info=True,
                )

            # Interruptible sleep — wakes immediately if stop() is called
            self._stop_event.wait(timeout=self._check_interval)
