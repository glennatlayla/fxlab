"""
Strategy draft and build contracts.

Pydantic v2 schemas for strategy lifecycle.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class StrategyDraftCreate(BaseModel):
    """
    Request payload to create a new strategy draft.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Draft strategy name")
    description: Optional[str] = Field(None, description="Strategy description")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy parameters (validation TBD)",
    )


class StrategyDraftUpdate(BaseModel):
    """
    Request payload to update an existing strategy draft.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class StrategyDraftResponse(BaseModel):
    """
    Response schema for strategy draft.
    """
    id: str = Field(..., description="ULID")
    user_id: str
    name: str
    description: Optional[str]
    parameters: Dict[str, Any]
    is_submitted: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StrategyBuildResponse(BaseModel):
    """
    Response schema for compiled strategy build.
    
    Phase 1/2 contract. Phase 3 consumes but does not mutate.
    """
    id: str = Field(..., description="ULID")
    name: str
    version: str
    artifact_uri: str
    source_hash: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# M2 additions — compiler interface contracts
# ---------------------------------------------------------------------------

class StrategyDefinition(BaseModel):
    """
    Input specification for a strategy to be compiled.

    Used as the input contract for the StrategyCompilerInterface.
    """
    id: str = Field(..., description="ULID of the strategy draft")
    name: str = Field(..., description="Human-readable strategy name")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy parameters",
    )
    version: Optional[str] = Field(None, description="Optional version tag")
    created_by: Optional[str] = Field(None, description="ULID of the owning user")


class CompiledStrategy(BaseModel):
    """
    Output of a successful strategy compilation step.

    Returned by StrategyCompilerInterface.compile().
    """
    id: str = Field(..., description="ULID of the compiled strategy artefact")
    strategy_id: str = Field(..., description="ULID of the source StrategyDefinition")
    artifact_uri: str = Field(..., description="Storage URI of the compiled artefact")
    source_hash: str = Field(..., description="SHA-256 of the source definition")
    version: str = Field(..., description="SemVer build tag")
    created_at: datetime = Field(default_factory=datetime.utcnow)
