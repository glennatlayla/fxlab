"""
Transaction Manager interface — explicit transaction boundary control.

Purpose:
    Define an abstract port for managing database transaction boundaries
    in service-layer code that needs to commit or roll back at specific
    points in a multi-step workflow (e.g. persist-then-call-external-service).

Responsibilities:
    - commit: Make all pending changes durable.
    - rollback: Discard all pending changes.

Does NOT:
    - Know about SQLAlchemy, PostgreSQL, or any concrete database.
    - Contain business logic.
    - Manage sessions or connections (concrete impl does that).

Dependencies:
    - None (pure interface).

Error conditions:
    - commit may raise ExternalServiceError on database failure.
    - rollback should never raise (best-effort).

Example:
    # In a service method that needs explicit commit boundaries:
    self._tx.commit()   # make order durable before broker call
    broker.submit(...)  # external call
    self._tx.commit()   # make post-broker updates durable
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TransactionManagerInterface(ABC):
    """
    Abstract port for explicit transaction boundary management.

    Injected into services that need to commit or roll back at
    specific points in a workflow — typically when an external
    call (broker, API, queue) happens between database writes.

    Concrete implementations wrap a database session (or a Unit
    of Work) and delegate commit/rollback to the underlying
    connection.

    Usage pattern:
        1. Service performs database writes (flush only).
        2. Service calls ``commit()`` to make writes durable.
        3. Service performs external call.
        4. Service updates database with external result.
        5. Service calls ``commit()`` again.

    If any step fails, the service calls ``rollback()`` to discard
    any pending (uncommitted) changes.

    Example:
        class LiveExecutionService:
            def __init__(self, *, tx: TransactionManagerInterface, ...):
                self._tx = tx

            def submit_order(self, ...):
                self._order_repo.save(...)
                self._tx.commit()       # durable before broker call
                broker_response = adapter.submit_order(...)
                self._order_repo.update_status(...)
                self._tx.commit()       # durable after broker response
    """

    @abstractmethod
    def commit(self) -> None:
        """
        Commit all pending database changes, making them durable.

        After a successful commit, changes are visible to other
        transactions and survive process restarts.

        Raises:
            ExternalServiceError: If the commit fails due to a
                database error (e.g. constraint violation, connection loss).
        """

    @abstractmethod
    def rollback(self) -> None:
        """
        Roll back all pending database changes since the last commit.

        This method should be safe to call at any time, even if there
        are no pending changes.  It should never raise — errors during
        rollback are logged but not propagated.
        """
