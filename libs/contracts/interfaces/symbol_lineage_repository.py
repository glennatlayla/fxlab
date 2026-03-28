"""
SymbolLineageRepositoryInterface — port for symbol data provenance access (M9).

Purpose:
    Define the contract that all symbol lineage repository implementations
    must honour, so that route handlers depend on an abstraction rather than
    on a concrete database adapter.

Responsibilities:
    - find_by_symbol() → SymbolLineageResponse for a given instrument.

Does NOT:
    - Compute lineage (handled by the service/domain layer).
    - Access feeds or runs directly.
    - Contain business logic.

Dependencies:
    - libs.contracts.symbol_lineage: SymbolLineageResponse.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - find_by_symbol raises NotFoundError when the symbol is unknown.

Example:
    class SqlSymbolLineageRepository(SymbolLineageRepositoryInterface):
        def find_by_symbol(self, symbol, correlation_id) -> SymbolLineageResponse: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.symbol_lineage import SymbolLineageResponse


class SymbolLineageRepositoryInterface(ABC):
    """
    Abstract port for symbol data provenance access.

    Implementations provide either a SQL-backed adapter (production) or
    an in-memory fake (tests).  All dependency injection targets this interface.
    """

    @abstractmethod
    def find_by_symbol(
        self, symbol: str, correlation_id: str
    ) -> SymbolLineageResponse:
        """
        Return the lineage record for a given instrument symbol.

        Args:
            symbol:         Instrument/ticker symbol string, e.g. 'AAPL'.
            correlation_id: Request-scoped tracing ID.

        Returns:
            SymbolLineageResponse with feeds and runs that reference this symbol.

        Raises:
            NotFoundError: If no lineage data exists for the given symbol.
        """
        ...
