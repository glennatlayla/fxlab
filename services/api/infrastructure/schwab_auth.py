"""
Schwab OAuth 2.0 token management.

Responsibilities:
- Manage OAuth 2.0 access/refresh token lifecycle for Schwab API.
- Automatically refresh expired access tokens using the refresh token.
- Provide thread-safe access to the current access token.
- Persist refresh tokens via SecretProvider for crash recovery.

Does NOT:
- Handle the initial browser-based authorization code flow (that is
  a one-time setup step performed by the operator).
- Contain business logic or broker operations.
- Make trading API calls (only OAuth token endpoint calls).

Dependencies:
- httpx: HTTP client for token endpoint requests.
- threading.Lock: Thread-safe token access.
- structlog: Structured logging.
- libs.contracts.schwab_config: SchwabConfig for OAuth URLs and credentials.

Error conditions:
- AuthError: Refresh token is invalid or revoked (requires re-authorization).
- ExternalServiceError: Token endpoint is unreachable.
- TransientError: 5xx/timeout from token endpoint (retriable).

Example:
    oauth = SchwabOAuthManager(config=schwab_config)
    oauth.initialize(refresh_token="initial_rt")
    token = oauth.get_access_token()  # Returns valid access token
    # ... later, token auto-refreshes on expiration
"""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass

import httpx
import structlog

from libs.contracts.errors import AuthError, ExternalServiceError, TransientError
from libs.contracts.schwab_config import SchwabConfig

logger = structlog.get_logger(__name__)

# Access tokens typically expire in 30 minutes for Schwab.
# Refresh 2 minutes before expiry to avoid edge-case failures.
_REFRESH_BUFFER_SECONDS = 120


@dataclass
class TokenState:
    """Internal token state container.

    Attributes:
        access_token: Current OAuth access token.
        refresh_token: Current OAuth refresh token.
        expires_at: Unix timestamp when the access token expires.
    """

    access_token: str
    refresh_token: str
    expires_at: float


class SchwabOAuthManager:
    """
    Thread-safe OAuth 2.0 token manager for Schwab API.

    Responsibilities:
    - Store current access and refresh tokens in memory.
    - Automatically refresh the access token before expiry.
    - Provide thread-safe get_access_token() for concurrent request handlers.
    - Log all token lifecycle events for debugging.

    Does NOT:
    - Handle the initial authorization code flow.
    - Make trading API calls.
    - Persist tokens to disk (caller provides initial refresh token).

    Dependencies:
    - SchwabConfig for OAuth endpoint URLs and client credentials.
    - httpx.Client for HTTP requests to the token endpoint.
    - threading.Lock for thread safety.

    Raises:
    - AuthError: Refresh token revoked or invalid.
    - ExternalServiceError: Token endpoint unreachable.
    - TransientError: Temporary failure (5xx, timeout).

    Example:
        manager = SchwabOAuthManager(config=schwab_config)
        manager.initialize(refresh_token="rt_from_secret_store")
        token = manager.get_access_token()
    """

    def __init__(
        self,
        config: SchwabConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """
        Initialize the OAuth manager.

        Args:
            config: Schwab configuration with OAuth URLs and credentials.
            http_client: Optional httpx.Client for testing. Creates one if None.
        """
        self._config = config
        self._client = http_client or httpx.Client(timeout=30.0)
        self._lock = threading.Lock()
        self._token_state: TokenState | None = None

    def initialize(self, refresh_token: str) -> None:
        """
        Initialize with a refresh token and obtain the first access token.

        This MUST be called before get_access_token(). The refresh token
        is typically loaded from a SecretProvider on application startup.

        Args:
            refresh_token: Valid OAuth refresh token from a prior authorization.

        Raises:
            AuthError: If the refresh token is invalid or revoked.
            ExternalServiceError: If the token endpoint is unreachable.
        """
        logger.info(
            "schwab_oauth.initialize",
            component="schwab_auth",
        )
        self._refresh(refresh_token)

    def get_access_token(self) -> str:
        """
        Return a valid access token, refreshing if necessary.

        Thread-safe: multiple concurrent callers may invoke this. Only one
        will perform the refresh; others wait on the lock.

        Returns:
            Valid OAuth access token string.

        Raises:
            AuthError: If no token state exists (initialize not called)
                or if the refresh token is revoked.
            ExternalServiceError: If the token endpoint is unreachable.
        """
        with self._lock:
            if self._token_state is None:
                raise AuthError("SchwabOAuthManager not initialized. Call initialize() first.")

            # Check if access token needs refresh
            if time.time() >= (self._token_state.expires_at - _REFRESH_BUFFER_SECONDS):
                logger.info(
                    "schwab_oauth.auto_refresh",
                    component="schwab_auth",
                    reason="token_expiring",
                )
                self._refresh(self._token_state.refresh_token)

            return self._token_state.access_token

    @property
    def current_refresh_token(self) -> str | None:
        """Return the current refresh token for persistence."""
        with self._lock:
            return self._token_state.refresh_token if self._token_state else None

    @property
    def is_initialized(self) -> bool:
        """Return whether initialize() has been called successfully."""
        with self._lock:
            return self._token_state is not None

    def _refresh(self, refresh_token: str) -> None:
        """
        Exchange a refresh token for a new access/refresh token pair.

        Updates internal token state. Called by initialize() and
        get_access_token() when the current token is expiring.

        Args:
            refresh_token: The refresh token to exchange.

        Raises:
            AuthError: 401/400 from token endpoint (token revoked).
            ExternalServiceError: Other non-retriable errors.
            TransientError: 5xx or timeout from token endpoint.
        """
        # Schwab requires Basic auth: base64(client_id:client_secret)
        credentials = base64.b64encode(
            f"{self._config.client_id}:{self._config.client_secret}".encode()
        ).decode()

        try:
            response = self._client.post(
                self._config.token_url,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "schwab_oauth.refresh_timeout",
                component="schwab_auth",
                error=str(exc),
            )
            raise TransientError(f"Schwab token endpoint timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            logger.error(
                "schwab_oauth.refresh_connection_error",
                component="schwab_auth",
                error=str(exc),
            )
            raise ExternalServiceError(f"Schwab token endpoint unreachable: {exc}") from exc

        if response.status_code in (400, 401):
            logger.error(
                "schwab_oauth.refresh_token_revoked",
                status_code=response.status_code,
                component="schwab_auth",
            )
            raise AuthError(
                "Schwab refresh token is invalid or revoked. "
                "Re-authorize the application via the Schwab developer portal."
            )

        if response.status_code >= 500:
            logger.warning(
                "schwab_oauth.refresh_server_error",
                status_code=response.status_code,
                component="schwab_auth",
            )
            raise TransientError(f"Schwab token endpoint returned {response.status_code}")

        if response.status_code != 200:
            logger.error(
                "schwab_oauth.refresh_unexpected_status",
                status_code=response.status_code,
                component="schwab_auth",
            )
            raise ExternalServiceError(
                f"Schwab token endpoint returned unexpected status {response.status_code}"
            )

        data = response.json()
        self._token_state = TokenState(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=time.time() + data.get("expires_in", 1800),
        )

        logger.info(
            "schwab_oauth.refresh_success",
            expires_in=data.get("expires_in", 1800),
            component="schwab_auth",
        )
