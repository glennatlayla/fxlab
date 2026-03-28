"""
Symbol lineage contracts (Phase 3 — M9: Symbol Lineage & Audit Explorer Backend).

Purpose:
    Provide the data shapes for symbol-level data provenance: which feeds supply
    data for a given instrument/symbol, and which runs have consumed it.

Responsibilities:
    - SymbolFeedRef — reference to a feed that provides data for the symbol.
    - SymbolRunRef  — reference to a run that consumed the symbol.
    - SymbolLineageResponse — aggregate provenance record for GET /symbols/{symbol}/lineage.

Does NOT:
    - Compute lineage (belongs in the service/domain layer).
    - Access the database directly.
    - Contain governance or certification logic.

Example:
    resp = SymbolLineageResponse(
        symbol="AAPL",
        feeds=[
            SymbolFeedRef(
                feed_id="01HQFEED0AAAAAAAAAAAAAAAA0",
                feed_name="AAPL_1m_primary",
                first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ],
        runs=[
            SymbolRunRef(
                run_id="01HQRUN0AAAAAAAAAAAAAAAA01",
                started_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
        ],
        generated_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SymbolFeedRef(BaseModel):
    """
    Reference to a data feed that provides data for a given symbol.

    Purpose:
        Inform the lineage viewer which feeds are sources of truth for this
        instrument, so operators know where the symbol's data originates.

    Responsibilities:
        - Carry feed identity (feed_id ULID, feed_name).
        - Record the timestamp when this feed first provided data for the symbol.

    Does NOT:
        - Report feed health (use GET /feed-health for that).

    Example:
        ref = SymbolFeedRef(
            feed_id="01HQFEED0AAAAAAAAAAAAAAAA0",
            feed_name="AAPL_1m_primary",
            first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    """

    feed_id: str = Field(..., description="ULID of the feed")
    feed_name: str = Field(..., description="Human-readable feed name")
    first_seen: datetime = Field(
        ..., description="Timestamp when this feed first supplied data for the symbol"
    )

    class Config:
        from_attributes = True


class SymbolRunRef(BaseModel):
    """
    Reference to a research/optimization run that consumed a given symbol.

    Purpose:
        Inform the lineage viewer which runs have used this symbol's data,
        supporting the research-launch feed-blocker check in §8.6.

    Responsibilities:
        - Carry run identity (run_id ULID).
        - Record when the run started (correlates with feed data windows).

    Does NOT:
        - Report run results (use GET /runs/{run_id}/results for that).

    Example:
        ref = SymbolRunRef(
            run_id="01HQRUN0AAAAAAAAAAAAAAAA01",
            started_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
    """

    run_id: str = Field(..., description="ULID of the run that consumed this symbol")
    started_at: datetime = Field(..., description="Timestamp when the run started")

    class Config:
        from_attributes = True


class SymbolLineageResponse(BaseModel):
    """
    Aggregate data provenance record for a single symbol.

    Purpose:
        Returned by GET /symbols/{symbol}/lineage to give the operator a
        complete picture of which feeds supply data for this symbol and
        which runs have consumed it.

    Responsibilities:
        - Report the symbol identifier.
        - List all feeds that provide data for this symbol.
        - List all runs that have consumed this symbol's data.
        - Carry a generation timestamp.

    Does NOT:
        - Include live feed health (use /feed-health for that).
        - Include run results (use /runs/{run_id}/results for that).
        - Compute lineage (handled by the repository/service layer).

    Example:
        resp = SymbolLineageResponse(
            symbol="AAPL",
            feeds=[SymbolFeedRef(...)],
            runs=[SymbolRunRef(...)],
            generated_at=datetime.now(timezone.utc),
        )
    """

    symbol: str = Field(..., description="Instrument / ticker symbol, e.g. 'AAPL'")
    feeds: list[SymbolFeedRef] = Field(
        default_factory=list,
        description="Feeds that supply data for this symbol",
    )
    runs: list[SymbolRunRef] = Field(
        default_factory=list,
        description="Runs that have consumed data for this symbol",
    )
    generated_at: datetime = Field(..., description="Response generation timestamp")
