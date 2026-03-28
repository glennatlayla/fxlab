"""
Symbol Lineage API endpoint (Phase 3 — M9: Symbol Lineage & Audit Explorer Backend).

Purpose:
    Expose the data provenance record for a given instrument/ticker symbol,
    showing which feeds supply data for it and which runs have consumed it.

Responsibilities:
    - GET /symbols/{symbol}/lineage — return SymbolLineageResponse for a symbol.
    - Provide get_symbol_lineage_repository() DI factory for dependency injection.
    - Serialize SymbolLineageResponse, SymbolFeedRef, SymbolRunRef via JSONResponse.

Does NOT:
    - Compute lineage (handled by the repository/service layer).
    - Write or update lineage data.
    - Access feeds or runs directly.

Dependencies:
    - SymbolLineageRepositoryInterface (injected via Depends).
    - SymbolLineageResponse, SymbolFeedRef, SymbolRunRef (domain contracts).
    - NotFoundError (domain exception → HTTP 404).

Error conditions:
    - GET /symbols/{symbol}/lineage raises HTTP 404 when the repository raises NotFoundError.

Known lessons:
    LL-007: No Optional[str] fields in serialized output — all use str defaults.
    LL-008: Use JSONResponse + model_dump() instead of response_model= for serialization.

Example:
    GET /symbols/AAPL/lineage
    → {
        "symbol": "AAPL",
        "feeds": [{"feed_id": "...", "feed_name": "...", "first_seen": "..."}],
        "runs": [{"run_id": "...", "started_at": "..."}],
        "generated_at": "..."
      }
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.symbol_lineage_repository import (
    SymbolLineageRepositoryInterface,
)
from libs.contracts.symbol_lineage import SymbolFeedRef, SymbolLineageResponse, SymbolRunRef

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection provider
# ---------------------------------------------------------------------------


def get_symbol_lineage_repository() -> SymbolLineageRepositoryInterface:
    """
    DI factory for SymbolLineageRepositoryInterface.

    Returns a MockSymbolLineageRepository bootstrap stub.  The real SQL-backed
    implementation will be wired in the lifespan DI container (ISS-022).

    Returns:
        SymbolLineageRepositoryInterface implementation.
    """
    from libs.contracts.mocks.mock_symbol_lineage_repository import (  # pragma: no cover
        MockSymbolLineageRepository,  # pragma: no cover
    )
    return MockSymbolLineageRepository()  # pragma: no cover


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_feed_ref(ref: SymbolFeedRef) -> dict:
    """
    Serialize a SymbolFeedRef to a JSON-safe dict.

    Args:
        ref: SymbolFeedRef domain object.

    Returns:
        JSON-serializable dict with feed_id, feed_name, first_seen fields.

    Example:
        d = _serialize_feed_ref(ref)
        # d["feed_id"] == "01HQFEED0AAAAAAAAAAAAAAAA1"
    """
    return {
        "feed_id": ref.feed_id,
        "feed_name": ref.feed_name,
        "first_seen": ref.first_seen.isoformat(),
    }


def _serialize_run_ref(ref: SymbolRunRef) -> dict:
    """
    Serialize a SymbolRunRef to a JSON-safe dict.

    Args:
        ref: SymbolRunRef domain object.

    Returns:
        JSON-serializable dict with run_id and started_at fields.

    Example:
        d = _serialize_run_ref(ref)
        # d["run_id"] == "01HQRUN0AAAAAAAAAAAAAAAA01"
    """
    return {
        "run_id": ref.run_id,
        "started_at": ref.started_at.isoformat(),
    }


def _serialize_lineage(lineage: SymbolLineageResponse) -> dict:
    """
    Serialize a SymbolLineageResponse to a JSON-safe dict.

    Args:
        lineage: SymbolLineageResponse domain object.

    Returns:
        JSON-serializable dict matching the SymbolLineageResponse shape:
        {symbol, feeds, runs, generated_at}.

    Example:
        d = _serialize_lineage(lineage)
        # d["symbol"] == "AAPL"
        # len(d["feeds"]) == 2
    """
    return {
        "symbol": lineage.symbol,
        "feeds": [_serialize_feed_ref(f) for f in lineage.feeds],
        "runs": [_serialize_run_ref(r) for r in lineage.runs],
        "generated_at": lineage.generated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/{symbol}/lineage")
def get_symbol_lineage(
    symbol: str,
    x_correlation_id: str = Header(default="no-corr"),
    repo: SymbolLineageRepositoryInterface = Depends(get_symbol_lineage_repository),
) -> JSONResponse:
    """
    Return the data provenance record for the given instrument symbol.

    Args:
        symbol:           Instrument/ticker symbol, e.g. 'AAPL'.
        x_correlation_id: Request-scoped tracing ID from HTTP header.
        repo:             Injected SymbolLineageRepositoryInterface.

    Returns:
        JSONResponse 200 with shape:
        {symbol, feeds: [{feed_id, feed_name, first_seen}],
         runs: [{run_id, started_at}], generated_at}.

    Raises:
        HTTPException 404: If no lineage data exists for the given symbol.

    Example:
        GET /symbols/AAPL/lineage
        → {"symbol": "AAPL", "feeds": [...], "runs": [...], "generated_at": "..."}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "symbol_lineage.requested",
        operation="get_symbol_lineage",
        correlation_id=corr,
        component="symbol_lineage_router",
        symbol=symbol,
    )
    try:
        lineage = repo.find_by_symbol(symbol, correlation_id=corr)
    except NotFoundError as exc:
        logger.info(
            "symbol_lineage.not_found",
            operation="get_symbol_lineage",
            correlation_id=corr,
            component="symbol_lineage_router",
            symbol=symbol,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "symbol_lineage.completed",
        operation="get_symbol_lineage",
        correlation_id=corr,
        component="symbol_lineage_router",
        symbol=symbol,
        feed_count=len(lineage.feeds),
        run_count=len(lineage.runs),
        result="success",
    )
    return JSONResponse(content=_serialize_lineage(lineage))
