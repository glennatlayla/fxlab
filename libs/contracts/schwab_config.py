"""
Schwab (formerly TD Ameritrade) broker configuration model.

Responsibilities:
- Define the configuration schema for Schwab API authentication.
- Validate OAuth 2.0 credentials, API URLs, and account identifiers.
- Provide factory methods for paper and live trading environments.

Does NOT:
- Store or manage secrets (that's the SecretProvider's job).
- Make API calls or validate credentials against Schwab.
- Manage OAuth token lifecycle (that's SchwabOAuthManager's job).

Dependencies:
- pydantic: Validation and serialization.

Error conditions:
- ValidationError: Missing or invalid configuration fields.

Example:
    config = SchwabConfig(
        client_id="app-abc123",
        client_secret="secret-xyz",
        redirect_uri="https://localhost/callback",
        account_hash="ENCRYPTED_ACCOUNT_HASH",
    )
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SchwabConfig(BaseModel):
    """
    Pydantic configuration model for Schwab Trading API.

    Schwab uses OAuth 2.0 for authentication. The initial authorization code
    is obtained through a browser-based flow. After that, the refresh token
    is used for unattended operation.

    Attributes:
        client_id: Schwab developer application client ID.
        client_secret: Schwab developer application client secret.
        redirect_uri: OAuth redirect URI registered with Schwab.
        account_hash: Encrypted account hash from Schwab (identifies the
            trading account). Obtained via GET /accounts endpoint.
        base_url: Schwab API base URL.
            Paper: https://api.schwabapi.com/trader/v1 (sandbox)
            Live: https://api.schwabapi.com/trader/v1
        auth_url: OAuth authorization endpoint.
        token_url: OAuth token endpoint.
        refresh_token: Optional initial refresh token for unattended startup.
            When provided, the adapter can authenticate without a browser flow.

    Example:
        config = SchwabConfig(
            client_id="app-abc123",
            client_secret="secret-xyz",
            redirect_uri="https://localhost/callback",
            account_hash="ENCRYPTED_HASH",
        )
        # config.orders_url == "https://api.schwabapi.com/trader/v1/accounts/ENCRYPTED_HASH/orders"
    """

    model_config = ConfigDict(frozen=True)

    client_id: str = Field(
        ...,
        min_length=1,
        description="Schwab developer application client ID.",
    )
    client_secret: str = Field(
        ...,
        min_length=1,
        description="Schwab developer application client secret.",
    )
    redirect_uri: str = Field(
        default="https://localhost/callback",
        description="OAuth redirect URI registered with Schwab.",
    )
    account_hash: str = Field(
        ...,
        min_length=1,
        description="Encrypted account hash from Schwab.",
    )
    base_url: str = Field(
        default="https://api.schwabapi.com/trader/v1",
        description="Schwab API base URL.",
    )
    auth_url: str = Field(
        default="https://api.schwabapi.com/v1/oauth/authorize",
        description="OAuth authorization endpoint.",
    )
    token_url: str = Field(
        default="https://api.schwabapi.com/v1/oauth/token",
        description="OAuth token endpoint.",
    )
    refresh_token: str | None = Field(
        default=None,
        description="Initial refresh token for unattended startup.",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Strip trailing slash for consistent URL construction."""
        return v.rstrip("/")

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def paper(
        cls,
        *,
        client_id: str,
        client_secret: str,
        account_hash: str,
        redirect_uri: str = "https://localhost/callback",
        refresh_token: str | None = None,
    ) -> SchwabConfig:
        """
        Create a Schwab config for paper trading (sandbox).

        Args:
            client_id: Schwab developer application client ID.
            client_secret: Schwab developer application client secret.
            account_hash: Encrypted account hash.
            redirect_uri: OAuth redirect URI.
            refresh_token: Optional initial refresh token.

        Returns:
            SchwabConfig configured for the Schwab sandbox environment.
        """
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            account_hash=account_hash,
            redirect_uri=redirect_uri,
            base_url="https://api.schwabapi.com/trader/v1",
            refresh_token=refresh_token,
        )

    @classmethod
    def live(
        cls,
        *,
        client_id: str,
        client_secret: str,
        account_hash: str,
        redirect_uri: str = "https://localhost/callback",
        refresh_token: str | None = None,
    ) -> SchwabConfig:
        """
        Create a Schwab config for live trading.

        Args:
            client_id: Schwab developer application client ID.
            client_secret: Schwab developer application client secret.
            account_hash: Encrypted account hash.
            redirect_uri: OAuth redirect URI.
            refresh_token: Optional initial refresh token.

        Returns:
            SchwabConfig configured for live Schwab trading.
        """
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            account_hash=account_hash,
            redirect_uri=redirect_uri,
            base_url="https://api.schwabapi.com/trader/v1",
            refresh_token=refresh_token,
        )

    # ------------------------------------------------------------------
    # URL properties
    # ------------------------------------------------------------------

    @property
    def orders_url(self) -> str:
        """Full URL for the orders endpoint."""
        return f"{self.base_url}/accounts/{self.account_hash}/orders"

    @property
    def account_url(self) -> str:
        """Full URL for the account endpoint."""
        return f"{self.base_url}/accounts/{self.account_hash}"

    @property
    def positions_url(self) -> str:
        """Full URL for the positions (included in account response)."""
        return f"{self.base_url}/accounts/{self.account_hash}?fields=positions"
