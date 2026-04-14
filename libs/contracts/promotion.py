"""
Promotion workflow contracts.

Defines request/response models for strategy promotion workflows.
"""

from pydantic import Field

from libs.contracts.base import FXLabBaseModel
from libs.contracts.enums import Environment, PromotionStatus


class PromotionRequest(FXLabBaseModel):
    """
    Request to promote a strategy candidate to a target environment.
    """

    candidate_id: str = Field(
        ...,
        description="ULID of the strategy candidate to promote",
        pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$",
    )
    target_environment: Environment = Field(
        ...,
        description="Target environment for promotion",
    )
    requester_id: str = Field(
        ...,
        description="ULID of the user requesting promotion",
        pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$",
    )
    notes: str | None = Field(
        None,
        description="Optional notes for the promotion request",
    )


class PromotionJobResponse(FXLabBaseModel):
    """
    Response from a promotion request indicating async job status.
    """

    job_id: str = Field(
        ...,
        description="ULID of the promotion job for tracking",
        pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$",
    )
    status: PromotionStatus = Field(
        ...,
        description="Initial status of the promotion job",
    )
