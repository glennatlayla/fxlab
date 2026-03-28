"""
Base models and response wrappers.

Provides foundation classes used across all contract definitions.
"""
import re
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

import structlog
from pydantic import BaseModel, ConfigDict, Field
from pydantic import BaseModel, ConfigDict


class FXLabBaseModel(BaseModel):
    """Base model for all FXLab domain objects."""
    
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        use_enum_values=False,
    )


T = TypeVar('T')


class APIResponse(BaseModel, Generic[T]):
    """
    Standard API response envelope.
    
    Wraps all API responses with consistent success flag and optional data.
    """
    success: bool
    data: T | None = None
    error: str | None = None

# -- merged (accumulator): libs/contracts/base.py --
ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')

# -- merged (accumulator): libs/contracts/base.py --
def validate_ulid(v: str) -> str:
    """Validate ULID format."""
    if not ULID_PATTERN.match(v):
        raise ValueError(f"Invalid ULID format: {v}")
    return v

ULID = Annotated[str, Field(pattern=r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')]

# -- merged (accumulator): libs/contracts/base.py --
logger = structlog.get_logger(__name__)

# -- merged (accumulator): libs/contracts/base.py --
def is_valid_ulid(value: str) -> bool:
    """Check if a string is a valid ULID."""
    return bool(ULID_PATTERN.match(value))

def ulid_field(description: str = "ULID identifier") -> Field:
    """Create a ULID field with standard validation."""
    return Field(..., description=description, pattern=r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')

# -- merged (accumulator): libs/contracts/base.py --
class ULIDModel(FXLabBaseModel):
    """Base model for entities with ULID primary keys."""
    id: str = Field(..., pattern=r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class TimestampedModel(FXLabBaseModel):
    """Base model for entities that track creation and update times."""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# -- merged (accumulator): libs/contracts/base.py --
class ULIDField(str):
    """
    String subclass that validates ULID format.
    
    Used in path parameters and request bodies where ULID validation is required.
    """
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("ULID must be a string")
        if not ULID_PATTERN.match(v):
            raise ValueError(f"Invalid ULID format: {v}")
        return v
