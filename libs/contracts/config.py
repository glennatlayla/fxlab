"""Configuration models."""
from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """Database configuration."""
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
    """MinIO configuration."""
    host: str = Field(default="localhost")
    port: int = Field(default=9000)
    access_key: str = Field(default="minioadmin")
    secret_key: str = Field(default="minioadmin")
    secure: bool = Field(default=False)


class AppConfig(BaseModel):
    """Application configuration."""
    environment: str = Field(default="local")
    log_level: str = Field(default="INFO")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    minio: MinIOConfig = Field(default_factory=MinIOConfig)
