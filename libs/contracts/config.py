"""
Configuration models for FXLab services.

Purpose:
    Provide typed, validated configuration via Pydantic models.
    All credentials default to empty strings and MUST be supplied
    via environment variables or a secrets manager in production.

Does NOT:
    - Contain real credentials or secrets.
    - Fall back to vendor default passwords (e.g. "minioadmin").
"""

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """Database configuration.  Password must be injected via environment."""

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    name: str = Field(default="fxlab")
    user: str = Field(default="postgres")
    password: str = Field(default="")


class RedisConfig(BaseModel):
    """Redis configuration."""

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)


class MinIOConfig(BaseModel):
    """
    MinIO / S3-compatible object storage configuration.

    access_key and secret_key default to empty strings.  They MUST be
    provided via MINIO_ACCESS_KEY / MINIO_SECRET_KEY env vars or a
    secrets manager.  Vendor defaults like 'minioadmin' are never used.
    """

    host: str = Field(default="localhost")
    port: int = Field(default=9000)
    access_key: str = Field(default="")
    secret_key: str = Field(default="")
    secure: bool = Field(default=False)


class AppConfig(BaseModel):
    """Application configuration."""

    environment: str = Field(default="local")
    log_level: str = Field(default="INFO")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    minio: MinIOConfig = Field(default_factory=MinIOConfig)
