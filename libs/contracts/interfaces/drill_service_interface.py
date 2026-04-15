"""
Drill service interface (port).

Responsibilities:
- Define the abstract contract for drill execution and eligibility checks.
- Execute production readiness drills against deployments.
- Check live eligibility based on drill results.
- Retrieve drill history.

Does NOT:
- Implement drill logic (service responsibility).
- Access data stores directly.

Dependencies:
- libs.contracts.drill: DrillResult, DrillRequirement.

Error conditions:
- NotFoundError: deployment_id not found.

Example:
    service: DrillServiceInterface = DrillService(...)
    result = service.execute_drill(drill_type="kill_switch", deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.drill import DrillRequirement, DrillResult


class DrillServiceInterface(ABC):
    """
    Port interface for drill execution service.

    Implementations:
    - DrillService — production implementation (M9)
    """

    @abstractmethod
    def execute_drill(
        self,
        *,
        drill_type: str,
        deployment_id: str,
    ) -> DrillResult:
        """
        Execute a production readiness drill against a deployment.

        Args:
            drill_type: Type of drill (kill_switch, rollback, reconnect, failover).
            deployment_id: ULID of the deployment to test.

        Returns:
            DrillResult with pass/fail, MTTH, timeline, and discrepancies.

        Raises:
            NotFoundError: deployment not found.
            ValueError: invalid drill type.
        """
        ...

    @abstractmethod
    def check_live_eligibility(
        self,
        *,
        deployment_id: str,
    ) -> tuple[bool, list[DrillRequirement]]:
        """
        Check whether a deployment has passed all required drills for live.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Tuple of (eligible: bool, missing_requirements: list[DrillRequirement]).
            If eligible is True, missing_requirements is empty.

        Raises:
            NotFoundError: deployment not found.
        """
        ...

    @abstractmethod
    def get_drill_history(
        self,
        *,
        deployment_id: str,
    ) -> list[DrillResult]:
        """
        Retrieve all drill results for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of DrillResult ordered by execution time.
        """
        ...
