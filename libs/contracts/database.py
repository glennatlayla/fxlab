"""Database connection and configuration contracts."""

from pydantic import BaseModel, Field, SecretStr, field_validator
from enum import Enum


class DatabaseType(str, Enum):
    """Supported database types."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLITE = "sqlite"


class DatabaseConfig(BaseModel):
    """Database connection configuration.
    
    Attributes:
        db_type: Database engine type.
        host: Database server hostname.
        port: Database server port.
        database: Database name.
        username: Connection username.
        password: Connection password (secret).
        pool_size: Connection pool size.
        max_overflow: Maximum overflow connections.
        pool_timeout_seconds: Pool acquisition timeout.
        echo_sql: Whether to log SQL statements.
    """
    db_type: DatabaseType = Field(..., description="Database engine")
    host: str = Field(..., description="Database host")
    port: int = Field(..., gt=0, lt=65536, description="Database port")
    database: str = Field(..., description="Database name")
    username: str = Field(..., description="Database user")
    password: SecretStr = Field(..., description="Database password")
    pool_size: int = Field(5, ge=1, description="Connection pool size")
    max_overflow: int = Field(10, ge=0, description="Max overflow connections")
    pool_timeout_seconds: int = Field(30, ge=1, description="Pool timeout")
    echo_sql: bool = Field(False, description="Log SQL statements")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Ensure host is not empty."""
        if not v or not v.strip():
            raise ValueError("host must not be empty")
        return v.strip()

    @field_validator("database")
    @classmethod
    def validate_database(cls, v: str) -> str:
        """Ensure database name is not empty."""
        if not v or not v.strip():
            raise ValueError("database must not be empty")
        return v.strip()
