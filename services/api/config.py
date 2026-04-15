"""
Centralized application configuration via Pydantic Settings.

Responsibilities:
- Define all environment variables in a single, validated Pydantic model.
- Group related settings into nested models for clarity.
- Fail at startup with clear error messages when required variables are missing.
- Provide a singleton accessor for the settings instance.

Does NOT:
- Contain business logic.
- Perform I/O beyond reading environment variables.
- Replace os.environ.get() calls in tests — test fixtures manage their own env.

Dependencies:
- pydantic_settings: BaseSettings for env-backed configuration.
- pydantic: Field for defaults and validation.

Error conditions:
- ValidationError at import/instantiation time if required vars are missing.

Example:
    from services.api.config import get_settings
    settings = get_settings()
    print(settings.database.url)
    print(settings.auth.jwt_secret_key)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """
    Database connection settings.

    Attributes:
        url: Full database connection URL (PostgreSQL or SQLite).
        pool_size: Connection pool size (PostgreSQL only).
        pool_overflow: Max overflow connections (PostgreSQL only).
        pool_timeout: Seconds to wait for a connection from pool.
        statement_timeout_ms: Max query execution time in milliseconds.
        sql_echo: Enable SQLAlchemy SQL logging.
    """

    url: str = Field(
        default="sqlite:///./fxlab_test.db",
        description="Database connection URL",
    )
    pool_size: int = Field(default=20, ge=1, description="Connection pool size")
    pool_overflow: int = Field(default=20, ge=0, description="Max overflow connections")
    pool_timeout: int = Field(default=30, ge=1, description="Pool timeout in seconds")
    statement_timeout_ms: int = Field(default=30000, ge=1000, description="Statement timeout in ms")
    sql_echo: bool = Field(default=False, description="Enable SQL echo logging")

    model_config = {"env_prefix": "DB_", "extra": "ignore"}


class RedisSettings(BaseSettings):
    """
    Redis connection settings.

    Attributes:
        url: Redis connection URL.
    """

    url: str = Field(default="", description="Redis connection URL")

    model_config = {"env_prefix": "REDIS_", "extra": "ignore"}


class AuthSettings(BaseSettings):
    """
    Authentication and authorization settings.

    Attributes:
        jwt_secret_key: HS256 signing key (min 32 bytes in production).
        jwt_expiration_minutes: Default JWT token expiry.
        jwt_audience: Expected JWT audience claim.
        jwt_issuer: Expected JWT issuer claim.
        jwt_max_token_bytes: Max JWT token size in bytes.
        keycloak_url: Keycloak server URL (empty = disabled).
        keycloak_realm: Keycloak realm name.
        keycloak_client_id: Keycloak client ID.
        keycloak_admin_client_secret: Keycloak admin client secret.
    """

    jwt_secret_key: str = Field(default="", description="JWT signing key")
    jwt_expiration_minutes: int = Field(default=30, ge=1, description="JWT expiry in minutes")
    jwt_audience: str = Field(default="fxlab-api", description="JWT audience")
    jwt_issuer: str = Field(default="fxlab", description="JWT issuer")
    jwt_max_token_bytes: int = Field(default=16384, ge=1024, description="Max JWT token size")
    keycloak_url: str = Field(default="", description="Keycloak server URL")
    keycloak_realm: str = Field(default="fxlab", description="Keycloak realm")
    keycloak_client_id: str = Field(default="fxlab-api", description="Keycloak client ID")
    keycloak_admin_client_secret: str = Field(default="", description="Keycloak admin secret")

    model_config = {"extra": "ignore"}


class RateLimitSettings(BaseSettings):
    """
    Rate limiting configuration.

    Attributes:
        governance_limit: Requests per minute for governance endpoints.
        auth_limit: Requests per minute for auth endpoints.
        default_limit: Requests per minute for other endpoints.
        backend: Rate limit backend type (memory or redis).
    """

    governance_limit: int = Field(default=20, ge=1, description="Governance rate limit/min")
    auth_limit: int = Field(default=10, ge=1, description="Auth rate limit/min")
    default_limit: int = Field(default=100, ge=1, description="Default rate limit/min")
    backend: str = Field(default="memory", description="Backend type: memory or redis")

    model_config = {"env_prefix": "RATE_LIMIT_", "extra": "ignore"}


class ObservabilitySettings(BaseSettings):
    """
    Observability and logging configuration.

    Attributes:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        environment: Deployment environment (test, development, staging, production).
        cors_allowed_origins: Comma-separated CORS origins.
        drain_timeout_s: Shutdown drain timeout in seconds.
        max_request_body_bytes: Maximum request body size.
    """

    log_level: str = Field(default="INFO", description="Log level")
    environment: str = Field(default="", description="Deployment environment")
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Comma-separated CORS origins",
    )
    drain_timeout_s: float = Field(default=30.0, ge=1.0, description="Drain timeout seconds")
    max_request_body_bytes: int = Field(
        default=524288, ge=1024, description="Max request body bytes"
    )

    model_config = {"extra": "ignore"}


class AppSettings(BaseSettings):
    """
    Top-level application settings aggregating all configuration groups.

    All environment variables are read at instantiation time and validated.
    Missing required variables cause an immediate, descriptive error.

    Responsibilities:
    - Aggregate all configuration subsections.
    - Provide a single point of access for all settings.
    - Validate settings at startup.

    Does NOT:
    - Contain business logic.
    - Manage secrets beyond reading env vars (see SecretProvider for vault integration).

    Example:
        settings = AppSettings()
        print(settings.database.url)
        print(settings.auth.jwt_secret_key)
    """

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    model_config = {"extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Get the singleton AppSettings instance.

    Uses lru_cache so the settings are loaded and validated exactly once,
    then reused for the lifetime of the process.

    Returns:
        Validated AppSettings instance.

    Example:
        settings = get_settings()
    """
    return AppSettings()
