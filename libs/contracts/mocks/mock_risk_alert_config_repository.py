"""
In-memory mock for risk alert config repository (testing only).

Responsibilities:
- Provide a test double for SqlRiskAlertConfigRepository.
- Store configs in memory for fast, isolated unit tests.
- Offer introspection helpers for assertions.

Does NOT:
- Persist to any database.
- Contain business logic.

Dependencies:
- libs.contracts.interfaces.risk_alert_config_repository

Example:
    repo = MockRiskAlertConfigRepository()
    repo.save(config)
    assert repo.count() == 1
"""

from __future__ import annotations

from libs.contracts.interfaces.risk_alert_config_repository import (
    RiskAlertConfigRepositoryInterface,
)
from libs.contracts.risk_alert import RiskAlertConfig


class MockRiskAlertConfigRepository(RiskAlertConfigRepositoryInterface):
    """
    In-memory mock for unit testing.

    Stores configs in a dict keyed by deployment_id. Supports all
    interface methods plus introspection helpers.

    Example:
        repo = MockRiskAlertConfigRepository()
        repo.save(config)
        assert repo.find_by_deployment_id("01H...") is not None
    """

    def __init__(self) -> None:
        self._store: dict[str, RiskAlertConfig] = {}

    def find_by_deployment_id(self, deployment_id: str) -> RiskAlertConfig | None:
        """Find by deployment_id."""
        return self._store.get(deployment_id)

    def save(self, config: RiskAlertConfig) -> RiskAlertConfig:
        """Save (upsert) config."""
        self._store[config.deployment_id] = config
        return config

    def find_all(self) -> list[RiskAlertConfig]:
        """List all configs."""
        return sorted(self._store.values(), key=lambda c: c.deployment_id)

    def find_all_enabled(self) -> list[RiskAlertConfig]:
        """List enabled configs."""
        return sorted(
            [c for c in self._store.values() if c.enabled],
            key=lambda c: c.deployment_id,
        )

    # Introspection helpers for tests
    def count(self) -> int:
        """Return number of stored configs."""
        return len(self._store)

    def clear(self) -> None:
        """Clear all stored configs."""
        self._store.clear()
