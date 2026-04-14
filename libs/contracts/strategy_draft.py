"""
Strategy draft and parameter definition contracts.

These models represent user-authored strategy drafts and parameter configurations
that will be compiled and executed by the research orchestration layer.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ParameterType(str, Enum):
    """Parameter data type enumeration."""

    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    CHOICE = "choice"


class ParameterDefinition(BaseModel):
    """
    Parameter definition for a strategy template.

    Defines validation constraints and UI presentation hints for a single parameter.
    """

    name: str = Field(..., description="Parameter identifier")
    display_name: str = Field(..., description="Human-readable parameter name")
    type: ParameterType = Field(..., description="Parameter data type")
    default: Any = Field(..., description="Default value for this parameter")
    required: bool = Field(default=True, description="Whether parameter is required")
    min_value: float | None = Field(
        default=None, description="Minimum value for numeric parameters"
    )
    max_value: float | None = Field(
        default=None, description="Maximum value for numeric parameters"
    )
    choices: list[str] | None = Field(
        default=None, description="Valid choices for CHOICE type parameters"
    )
    description: str | None = Field(default=None, description="Parameter documentation")


class StrategyDraftStatus(str, Enum):
    """Strategy draft lifecycle status."""

    EDITING = "editing"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    SUBMITTED = "submitted"


class StrategyDraftRequest(BaseModel):
    """
    Request to create or update a strategy draft.

    Represents user input from the strategy draft form UI.
    """

    name: str = Field(..., description="Strategy draft name", min_length=1, max_length=200)
    description: str | None = Field(
        default=None, description="Strategy description", max_length=2000
    )
    template_id: str = Field(..., description="Strategy template ULID")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parameter values keyed by parameter name"
    )


class StrategyDraft(BaseModel):
    """
    Strategy draft entity.

    Represents a user-authored strategy configuration that has not yet been compiled.
    """

    id: str = Field(..., description="Draft ULID")
    user_id: str = Field(..., description="Author user ULID")
    name: str = Field(..., description="Strategy draft name")
    description: str | None = Field(default=None, description="Strategy description")
    template_id: str = Field(..., description="Strategy template ULID")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parameter values keyed by parameter name"
    )
    status: StrategyDraftStatus = Field(..., description="Draft lifecycle status")
    validation_errors: list[str] = Field(
        default_factory=list, description="Validation error messages"
    )
    created_at: datetime = Field(..., description="Draft creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class StrategyDraftAutosaveRequest(BaseModel):
    """
    Autosave payload for draft persistence.

    Sent periodically from the UI to preserve in-progress work.
    """

    draft_id: str = Field(..., description="Draft ULID")
    parameters: dict[str, Any] = Field(..., description="Current parameter state")


class StrategyDraftAutosaveResponse(BaseModel):
    """
    Autosave confirmation response.

    Confirms successful persistence of draft state.
    """

    draft_id: str = Field(..., description="Draft ULID")
    saved_at: datetime = Field(..., description="Server-side save timestamp")
