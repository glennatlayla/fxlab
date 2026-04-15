"""
Stress test service interface (port).

Responsibilities:
- Define the abstract contract for stress testing operations.
- Specify scenario execution, predefined scenario listing, and custom scenario support.
- Serve as the dependency injection target for controllers and tests.

Does NOT:
- Implement stress test computation (service implementation responsibility).
- Fetch data (repository interfaces are injected into the implementation).
- Persist results (caller or cache layer responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: deployment has no positions.
- ValidationError: invalid scenario parameters.

Example:
    service: StressTestServiceInterface = StressTestService(
        position_repo=position_repo,
        risk_gate_service=risk_gate_service,
    )
    result = service.run_scenario(
        deployment_id="01HDEPLOY...",
        scenario=custom_scenario,
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.stress_test import (
    ScenarioLibrary,
    StressScenario,
    StressTestResult,
)


class StressTestServiceInterface(ABC):
    """
    Port interface for stress testing and scenario analysis.

    Responsibilities:
    - Execute custom stress scenarios against a deployment's portfolio.
    - Execute predefined scenarios from the historical library.
    - List available predefined scenarios.

    Does NOT:
    - Access databases directly (injected via repository interfaces).
    - Trigger actual risk actions (advisory only).
    - Cache results (caller responsibility).
    """

    @abstractmethod
    def run_scenario(
        self,
        *,
        deployment_id: str,
        scenario: StressScenario,
    ) -> StressTestResult:
        """
        Run a stress scenario against a deployment's portfolio.

        Applies the scenario's shocks to current positions and computes
        portfolio-level and per-symbol P&L impact.

        Args:
            deployment_id: ULID of the deployment to stress test.
            scenario: Stress scenario configuration with shocks.

        Returns:
            StressTestResult with impact analysis.

        Raises:
            NotFoundError: If the deployment has no positions.
        """
        ...

    @abstractmethod
    def run_predefined(
        self,
        *,
        deployment_id: str,
        scenario_name: ScenarioLibrary,
    ) -> StressTestResult:
        """
        Run a predefined scenario from the historical library.

        Args:
            deployment_id: ULID of the deployment to stress test.
            scenario_name: Predefined scenario identifier.

        Returns:
            StressTestResult with impact analysis.

        Raises:
            NotFoundError: If the deployment has no positions.
            ValidationError: If the scenario name is not in the library.
        """
        ...

    @abstractmethod
    def list_predefined_scenarios(self) -> list[StressScenario]:
        """
        List all available predefined stress scenarios.

        Returns:
            List of predefined StressScenario configurations.
        """
        ...
