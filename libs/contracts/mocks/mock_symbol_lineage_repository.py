"""
MockSymbolLineageRepository — in-memory SymbolLineageRepositoryInterface for unit tests (M9).

Purpose:
    Provide a fast, fully controllable fake implementation of
    SymbolLineageRepositoryInterface so that unit tests can exercise
    symbol lineage route handlers without a real database.

Responsibilities:
    - Store SymbolLineageResponse objects in memory, keyed by symbol.
    - Implement find_by_symbol() with the same error contract as the real implementation.
    - Provide save() and clear() introspection helpers for test setup/teardown.

Does NOT:
    - Connect to any database or external system.
    - Compute symbol-to-feed/run associations.

Dependencies:
    - SymbolLineageRepositoryInterface (parent).
    - SymbolLineageResponse (domain contract).
    - NotFoundError (typed exception).

Error conditions:
    - find_by_symbol raises NotFoundError for unknown symbols.

Example:
    repo = MockSymbolLineageRepository()
    repo.save(
        SymbolLineageResponse(
            symbol="AAPL",
            feeds=[...],
            runs=[...],
            generated_at=datetime.now(timezone.utc),
        )
    )
    lineage = repo.find_by_symbol("AAPL", correlation_id="test")
"""

from __future__ import annotations

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.symbol_lineage_repository import (
    SymbolLineageRepositoryInterface,
)
from libs.contracts.symbol_lineage import SymbolLineageResponse


class MockSymbolLineageRepository(SymbolLineageRepositoryInterface):
    """
    In-memory SymbolLineageRepositoryInterface for unit tests.

    Thread-safety: Not thread-safe.  Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Keyed by symbol string (case-sensitive).
        self._store: dict[str, SymbolLineageResponse] = {}

    # ------------------------------------------------------------------
    # SymbolLineageRepositoryInterface implementation
    # ------------------------------------------------------------------

    def find_by_symbol(
        self, symbol: str, correlation_id: str
    ) -> SymbolLineageResponse:
        """
        Return the lineage record for a given instrument symbol.

        Args:
            symbol:         Instrument/ticker symbol string.
            correlation_id: Ignored in mock; accepted for interface parity.

        Returns:
            SymbolLineageResponse for the given symbol.

        Raises:
            NotFoundError: If no lineage data has been saved for the symbol.

        Example:
            lineage = repo.find_by_symbol("AAPL", correlation_id="c")
        """
        if symbol not in self._store:
            raise NotFoundError(f"SymbolLineageResponse for symbol={symbol!r} not found")
        return self._store[symbol]

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def save(self, lineage: SymbolLineageResponse) -> None:
        """
        Persist a SymbolLineageResponse to the in-memory store.

        Args:
            lineage: SymbolLineageResponse to store; keyed by lineage.symbol.
        """
        self._store[lineage.symbol] = lineage

    def clear(self) -> None:
        """Remove all stored symbol lineage records."""
        self._store.clear()

    def count(self) -> int:
        """Return the number of stored symbol lineage records."""
        return len(self._store)
