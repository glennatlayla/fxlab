"""
In-memory mock incident repository for unit testing (Phase 6 — M13).

Purpose:
    Provide a test double for IncidentRepositoryInterface that stores
    incidents in a Python dict, enabling fast isolated unit tests
    without database dependencies.

Responsibilities:
    - Implement all IncidentRepositoryInterface methods in-memory.
    - Provide introspection helpers for test assertions.

Does NOT:
    - Persist data across test runs.
    - Enforce database constraints.

Dependencies:
    - IncidentRepositoryInterface (implements).
    - IncidentRecord, IncidentStatus contracts.
    - NotFoundError domain exception.

Example:
    repo = MockIncidentRepository()
    repo.save(incident)
    assert repo.count() == 1
"""

from __future__ import annotations

from datetime import datetime, timedelta

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.incident_repository_interface import (
    IncidentRepositoryInterface,
)
from libs.contracts.notification import IncidentRecord, IncidentStatus


class MockIncidentRepository(IncidentRepositoryInterface):
    """
    In-memory implementation of IncidentRepositoryInterface for unit testing.

    Stores incidents in a dict keyed by incident_id.

    Example:
        repo = MockIncidentRepository()
        repo.save(incident)
        found = repo.find_by_id(incident.incident_id)
    """

    def __init__(self) -> None:
        self._store: dict[str, IncidentRecord] = {}

    def save(self, incident: IncidentRecord) -> IncidentRecord:
        """
        Persist incident in memory.

        Args:
            incident: The incident record to save.

        Returns:
            The saved incident record.
        """
        self._store[incident.incident_id] = incident
        return incident

    def find_by_id(self, incident_id: str) -> IncidentRecord:
        """
        Retrieve an incident by ID.

        Args:
            incident_id: ULID of the incident.

        Returns:
            IncidentRecord for the given ID.

        Raises:
            NotFoundError: If the incident does not exist.
        """
        if incident_id not in self._store:
            raise NotFoundError(f"Incident {incident_id} not found")
        return self._store[incident_id]

    def find_open_incidents(self) -> list[IncidentRecord]:
        """
        List all incidents that are not resolved.

        Returns:
            List of IncidentRecord with status != RESOLVED.
        """
        return [inc for inc in self._store.values() if inc.status != IncidentStatus.RESOLVED]

    def find_unacknowledged_past_sla(
        self, severity_sla_map: dict[str, int], now: datetime
    ) -> list[IncidentRecord]:
        """
        Find triggered incidents past their SLA.

        Args:
            severity_sla_map: Maps severity value to SLA seconds.
            now: Current time for SLA comparison.

        Returns:
            List of IncidentRecord that are past their SLA deadline.
        """
        results: list[IncidentRecord] = []
        for inc in self._store.values():
            if inc.status != IncidentStatus.TRIGGERED:
                continue
            sla_seconds = severity_sla_map.get(inc.severity.value)
            if sla_seconds is None:
                continue
            deadline = inc.created_at + timedelta(seconds=sla_seconds)
            if now >= deadline:
                results.append(inc)
        return results

    # Introspection helpers for tests
    def get_all(self) -> list[IncidentRecord]:
        """Return all stored incidents."""
        return list(self._store.values())

    def count(self) -> int:
        """Return the number of stored incidents."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all stored incidents."""
        self._store.clear()
