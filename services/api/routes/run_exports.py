"""
Routes for ``GET /runs/{run_id}/exports/blotter.csv``.

Purpose:
    Stream the round-trip trade blotter for a completed research run as
    a CSV download for spreadsheet analysis. The blotter view (one row
    per closed round-trip with entry/exit times, units, prices, fees,
    realised PnL, and holding-period seconds) is the operator-facing
    counterpart to the JSON ``GET /runs/{run_id}/results/blotter`` endpoint
    that powers the in-app trade-blotter table.

Responsibilities:
    - Validate the ``run_id`` path parameter (ULID format) before calling
      the service.
    - Enforce the ``exports:read`` scope (matches the JSON blotter
      endpoint already consumed by the same operator role).
    - Stream the CSV body via :class:`StreamingResponse` so memory stays
      bounded for runs with very large blotters; the underlying service
      yields chunks of at most 1000 rows (see
      :data:`libs.contracts.run_results.RUN_BLOTTER_EXPORT_CHUNK_SIZE`).
    - Map domain exceptions onto HTTP status codes:
        * ``NotFoundError`` -> 404
        * ``RunNotCompletedError`` -> 409 (with the current status in the
          detail string so the frontend can render a targeted toast).
        * Any other exception -> 500 (logged with exc_info).

Does NOT:
    - Contain business logic (delegated to :class:`ExportService`).
    - Touch the database or storage directly.
    - Modify ``services/api/routes/runs.py`` or
      ``services/api/routes/exports.py``.

Dependencies:
    - :class:`ExportService` injected via :func:`set_export_service`
      / :func:`get_export_service` for testability.
    - :func:`require_scope` for ``exports:read`` enforcement.

Wire format:
    Response 200 — ``text/csv`` body. ``Content-Disposition`` header is
    ``attachment; filename="run-{run_id}-blotter.csv"`` so the browser
    triggers a download dialog instead of inlining the body.
"""

from __future__ import annotations

from collections.abc import Iterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse

from libs.contracts.errors import NotFoundError
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var
from services.api.routes.runs import is_valid_ulid
from services.api.services.export_service import ExportService
from services.api.services.research_run_service import RunNotCompletedError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/runs", tags=["run_exports"])


# ---------------------------------------------------------------------------
# Module-level DI for ExportService
# ---------------------------------------------------------------------------
#
# Mirrors the pattern used by ``services/api/routes/runs.py`` so the
# bootstrap code in ``services/api/main.py`` and the test suite both
# inject the concrete service the same way.

_export_service: ExportService | None = None


def set_export_service(service: ExportService | None) -> None:
    """
    Register the :class:`ExportService` instance for route injection.

    Called during application bootstrap (see ``services/api/main.py``)
    or in test setup. Passing ``None`` clears the registration, which is
    used by the route-test teardown to prevent leakage between files.

    Args:
        service: Concrete :class:`ExportService` instance with its
            ``research_run_repo`` dependency wired, or ``None`` to clear
            the registration.
    """
    global _export_service
    _export_service = service


def get_export_service() -> ExportService:
    """
    Retrieve the registered :class:`ExportService`.

    Returns:
        The registered service instance.

    Raises:
        HTTPException 503: If no service has been registered. Production
            bootstrap wires the service in :func:`services.api.main.lifespan`;
            a 503 here means the registration step was skipped or failed.
    """
    if _export_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run-exports service not configured.",
        )
    return _export_service


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/exports/blotter.csv
# ---------------------------------------------------------------------------


@router.get(
    "/{run_id}/exports/blotter.csv",
    summary="Stream the trade blotter for a completed run as CSV",
    response_class=StreamingResponse,
)
async def get_run_blotter_csv(
    run_id: str = Path(..., description="Run ULID"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ExportService = Depends(get_export_service),
) -> StreamingResponse:
    """
    Stream the round-trip trade blotter for ``run_id`` as CSV.

    The body is generated on the fly via the export service's chunked
    streamer; nothing is buffered in memory beyond a single chunk
    (1000 rows worst case). The response carries
    ``Content-Type: text/csv`` and a ``Content-Disposition: attachment``
    header so the browser presents a download dialog with the canonical
    filename ``run-{run_id}-blotter.csv``.

    Args:
        run_id: ULID of the research run to export.
        user: Authenticated caller; must hold ``exports:read``.
        service: Injected :class:`ExportService` (with its
            ``research_run_repo`` dependency wired by the bootstrap).

    Returns:
        :class:`StreamingResponse` carrying the chunked CSV body.

    Raises:
        HTTPException 422: ``run_id`` is not a valid ULID.
        HTTPException 404: No record exists for ``run_id``.
        HTTPException 409: Run exists but is in a non-terminal state
            (``pending``, ``queued``, ``running``).
        HTTPException 500: Any unexpected service-layer failure.
        HTTPException 503: Export service has not been wired into the
            route module (handled by the dependency).
        HTTPException 401 / 403: Missing or insufficient auth (handled by
            :func:`require_scope`).
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "run_blotter_csv.entry",
        run_id=run_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="run_exports",
    )

    # ULID format check happens BEFORE the service call so we surface 422
    # without paying for a repo lookup. Centralised regex matches the one
    # used by the JSON blotter endpoint.
    if not is_valid_ulid(run_id):
        logger.warning(
            "run_blotter_csv.invalid_ulid",
            run_id=run_id,
            correlation_id=corr_id,
            component="run_exports",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid ULID format",
        )

    # Drive the service eagerly enough to surface NotFound / NotCompleted
    # BEFORE we hand the iterator over to StreamingResponse. The service's
    # generator does its lookup + status check before yielding the first
    # chunk, so we yank the first chunk here, then stitch a wrapper that
    # re-emits it followed by the remainder.
    try:
        stream = service.stream_run_blotter_csv(run_id)
        try:
            first_chunk = next(stream)
        except StopIteration:
            # Defensive — the service always yields at least the header
            # row, so this branch should be unreachable. Surface as 500
            # rather than emitting an empty 200 body.
            logger.error(
                "run_blotter_csv.empty_stream",
                run_id=run_id,
                correlation_id=corr_id,
                component="run_exports",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error",
            )
    except NotFoundError as exc:
        logger.warning(
            "run_blotter_csv.not_found",
            run_id=run_id,
            correlation_id=corr_id,
            component="run_exports",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RunNotCompletedError as exc:
        logger.warning(
            "run_blotter_csv.not_completed",
            run_id=run_id,
            run_status=exc.status.value,
            correlation_id=corr_id,
            component="run_exports",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        # Already shaped — propagate unchanged.
        raise
    except Exception as exc:  # noqa: BLE001 — wrap-and-log unexpected failures
        logger.error(
            "run_blotter_csv.error",
            run_id=run_id,
            error=str(exc),
            exc_info=True,
            correlation_id=corr_id,
            component="run_exports",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from exc

    def _body_iter() -> Iterator[bytes]:
        """
        Re-emit the prefetched first chunk, then drain the rest of the
        service's generator. Wrapping a generator like this keeps the
        StreamingResponse memory-bounded; only one chunk is in memory at
        a time during the wire write.
        """
        yield first_chunk
        yield from stream

    filename = f"run-{run_id}-blotter.csv"
    response_headers = {
        # RFC 6266 attachment disposition with quoted filename so reserved
        # characters (e.g. semicolons in some run IDs) survive the round-trip.
        "Content-Disposition": f'attachment; filename="{filename}"',
        # Disable caching of the dynamic CSV body — fresh content per request
        # so spreadsheet users always pull the latest blotter view.
        "Cache-Control": "no-store",
    }

    logger.info(
        "run_blotter_csv.success",
        run_id=run_id,
        correlation_id=corr_id,
        component="run_exports",
    )

    return StreamingResponse(
        _body_iter(),
        media_type="text/csv",
        headers=response_headers,
    )
