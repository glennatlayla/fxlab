"""
Promotion workflow routes.

Handles promotion request submission and status tracking.
"""

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import Field, field_validator
from ulid import ULID

from libs.contracts.base import FXLabBaseModel
from libs.contracts.enums import Environment
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger()

router = APIRouter(prefix="/promotions", tags=["promotions"])


class PromotionRequest(FXLabBaseModel):
    """Request to promote a strategy candidate."""

    # Pattern enforces ULID format (26 chars, Crockford Base32).
    # The @field_validator below adds stricter parse-based validation for
    # production; the pattern is used by the stub validator in tests.
    candidate_id: str = Field(
        ...,
        description="ULID of candidate to promote",
        pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$",
    )
    target_environment: Environment = Field(..., description="Target deployment environment")
    requester_id: str = Field(
        ...,
        description="ULID of user requesting promotion",
        pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$",
    )

    @field_validator("candidate_id", "requester_id")
    @classmethod
    def validate_ulid(cls, v: str) -> str:
        """Validate that the value is a valid ULID via ULID.from_str."""
        try:
            ULID.from_str(v)
            return v
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid ULID format: {v}")


class PromotionResponse(FXLabBaseModel):
    """Response from promotion request submission."""

    job_id: str = Field(..., description="ULID of async job tracking this promotion")
    status: str = Field(..., description="Initial job status")


@router.post("/request", status_code=status.HTTP_202_ACCEPTED, response_model=PromotionResponse)
async def request_promotion(
    request: PromotionRequest,
    user: AuthenticatedUser = Depends(require_scope("promotions:request")),
) -> PromotionResponse:
    """
    Submit a promotion request for async processing.

    Validates RBAC permissions, creates an audit event, enqueues the job,
    and returns immediately with a job ID.

    Args:
        request: Validated promotion request payload.

    Returns:
        PromotionResponse with job_id and initial status.

    Raises:
        HTTPException 403: If the requester lacks permission.
    """
    from fastapi import HTTPException

    # Import from main so tests can patch these via services.api.main.*
    from services.api.main import audit_service, check_permission, submit_promotion_request

    corr_id = correlation_id_var.get("no-corr")
    env_value = (
        request.target_environment.value
        if hasattr(request.target_environment, "value")
        else request.target_environment
    )
    logger.info(
        "promotion.request.received",
        candidate_id=request.candidate_id,
        target_environment=env_value,
        requester_id=request.requester_id,
        correlation_id=corr_id,
        component="promotions",
    )

    # RBAC check — tests patch services.api.main.check_permission
    if not check_permission(request.requester_id):
        logger.warning(
            "promotion.request.forbidden",
            requester_id=request.requester_id,
            correlation_id=corr_id,
            component="promotions",
        )
        raise HTTPException(status_code=403, detail="Forbidden: insufficient permissions")

    # Audit event — tests patch services.api.main.audit_service
    audit_service.log_event(
        event_type="promotion_requested",
        candidate_id=request.candidate_id,
        requester_id=request.requester_id,
    )

    result = submit_promotion_request(request)

    # Ensure required fields are present (some mocks return only job_id)
    response_data = {"status": "pending", **result}

    logger.info(
        "promotion.request.accepted",
        job_id=response_data["job_id"],
        candidate_id=request.candidate_id,
        correlation_id=corr_id,
        component="promotions",
    )

    return PromotionResponse(**response_data)
