"""
Incident repository interface (Phase 6 — M13).

Purpose:
    Define the abstract port for incident persistence so the incident
    manager depends on an interface, not a concrete database implementation.

Responsibilities:
    - save: Persist a new or updated incident record.
    - find_by_id: Retrieve an incident by its ID.
    - find_open_incidents: List incidents not yet resolved.
    - find_unacknowledged_past_sla: Find triggered incidents past their SLA.

Does NOT:
    - Contain business logic.
    - Send notifications.

Dependencies:
    - IncidentRecord contract.

Example:
    class SqlIncidentRepository(IncidentRepositoryInterface):
        def save(self, incident: IncidentRecord) -> IncidentRecord:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.notification import IncidentRecord


class IncidentRepositoryInterface(ABC):
    """
    Abstract port for incident record persistence.

    Responsibilities:
        - CRUD operations for incident lifecycle tracking.
        - Query for incidents requiring escalation.

    Does NOT:
        - Contain escalation logic (incident manager responsibility).
        - Send notifications (notification service responsibility).

    Error conditions:
        - NotFoundError: If an incident_id is unknown.
    """

    @abstractmethod
    def save(self, incident: IncidentRecord) -> IncidentRecord:
        """
        Persist a new or updated incident record.

        Args:
            incident: The incident record to save.

        Returns:
            The saved incident record.
        """

    @abstractmethod
    def find_by_id(self, incident_id: str) -> IncidentRecord:
        """
        Retrieve an incident by its ID.

        Args:
            incident_id: ULID of the incident.

        Returns:
            IncidentRecord for the given ID.

        Raises:
            NotFoundError: If the incident does not exist.
        """

    @abstractmethod
    def find_open_incidents(self) -> list[IncidentRecord]:
        """
        List all incidents that are not yet resolved.

        Returns:
            List of IncidentRecord with status != RESOLVED.
        """

    @abstractmethod
    def find_unacknowledged_past_sla(
        self, severity_sla_map: dict[str, int], now: datetime
    ) -> list[IncidentRecord]:
        """
        Find triggered incidents that have not been acknowledged within their SLA.

        Args:
            severity_sla_map: Maps severity value (e.g., "P1") to SLA
                seconds (e.g., 900 for 15 minutes).
            now: Current time for SLA comparison.

        Returns:
            List of IncidentRecord that are past their SLA deadline.
        """
