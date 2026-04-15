"""
Kill switch service interface (port).

Responsibilities:
- Define the abstract contract for kill switch operations.
- Activation/deactivation of kill switches at global, strategy, symbol scopes.
- Emergency posture execution for deployments.
- Status query across all scopes.

Does NOT:
- Implement kill switch logic (service responsibility).
- Persist events (delegates to repository/ORM).

Dependencies:
- libs.contracts.safety: KillSwitchScope, KillSwitchStatus, HaltEvent,
  EmergencyPostureDecision.

Error conditions:
- NotFoundError: deployment_id or target_id not found.
- StateTransitionError: kill switch already in requested state.

Example:
    service: KillSwitchServiceInterface = KillSwitchService(...)
    event = service.activate_kill_switch(
        scope=KillSwitchScope.GLOBAL,
        target_id="global",
        reason="Emergency halt",
        activated_by="system:risk_gate",
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from libs.contracts.safety import (
    EmergencyPostureDecision,
    HaltEvent,
    HaltTrigger,
    KillSwitchScope,
    KillSwitchStatus,
)


class KillSwitchServiceInterface(ABC):
    """
    Port interface for kill switch service.

    Implementations:
    - KillSwitchService — production implementation (M7)
    """

    @abstractmethod
    def activate_kill_switch(
        self,
        *,
        scope: KillSwitchScope,
        target_id: str,
        reason: str,
        activated_by: str,
        trigger: HaltTrigger = HaltTrigger.KILL_SWITCH,
    ) -> HaltEvent:
        """
        Activate a kill switch at the given scope.

        Args:
            scope: Kill switch scope (global, strategy, symbol).
            target_id: Target identifier.
            reason: Human-readable activation reason.
            activated_by: Identity of the activator.
            trigger: What triggered this activation.

        Returns:
            HaltEvent recording the activation and MTTH.

        Raises:
            StateTransitionError: kill switch already active at this scope+target.
        """
        ...

    @abstractmethod
    def deactivate_kill_switch(
        self,
        *,
        scope: KillSwitchScope,
        target_id: str,
        deactivated_by: str,
    ) -> HaltEvent:
        """
        Deactivate a kill switch at the given scope.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.
            deactivated_by: Identity of the deactivator.

        Returns:
            HaltEvent with deactivation timestamp.

        Raises:
            NotFoundError: no active kill switch at this scope+target.
        """
        ...

    @abstractmethod
    def get_status(self) -> list[KillSwitchStatus]:
        """
        Get the current state of all kill switches.

        Returns:
            List of KillSwitchStatus for all active and recently
            deactivated switches.
        """
        ...

    @abstractmethod
    def is_halted(
        self,
        *,
        deployment_id: str,
        strategy_id: str | None = None,
        symbol: str | None = None,
    ) -> bool:
        """
        Check whether trading is halted for the given context.

        A deployment is halted if any of the following are active:
        - Global kill switch
        - Strategy kill switch matching strategy_id
        - Symbol kill switch matching symbol

        Args:
            deployment_id: ULID of the deployment.
            strategy_id: Optional strategy ULID to check.
            symbol: Optional symbol to check.

        Returns:
            True if any relevant kill switch is active.
        """
        ...

    @abstractmethod
    def execute_emergency_posture(
        self,
        *,
        deployment_id: str,
        trigger: HaltTrigger,
        reason: str,
    ) -> EmergencyPostureDecision:
        """
        Execute the declared emergency posture for a deployment.

        Looks up the deployment's declared posture and executes it:
        - flatten_all: Cancel open orders + close all positions.
        - cancel_open: Cancel open orders only.
        - hold: Do nothing (human intervention required).
        - custom: Strategy-specific logic.

        After executing the posture actions, runs a verification loop
        that polls broker positions every 1s for up to verification_timeout_s
        (default 30s). If any positions remain open after the timeout,
        logs CRITICAL with residual exposure details.

        Args:
            deployment_id: ULID of the deployment.
            trigger: What triggered the posture execution.
            reason: Human-readable reason.

        Returns:
            EmergencyPostureDecision recording what was done, including
            an EmergencyPostureVerification with position closure status
            and residual exposure for flatten_all/cancel_open postures.

        Raises:
            NotFoundError: deployment not found or no adapter registered.
        """
        ...

    @abstractmethod
    def verify_halt(self, *, scope: KillSwitchScope, target_id: str) -> dict[str, Any]:
        """
        Re-check all orders and positions in scope are cancelled and flat.

        For each adapter affected by the kill switch scope, queries open orders
        and positions. Returns verification results including any residual
        exposure.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.

        Returns:
            Dict with keys:
                - verified (bool): True if no residual open orders/positions.
                - open_orders_remaining (list[dict]): Any open orders found.
                - open_positions_remaining (list[dict]): Any open positions.
                - residual_exposure (dict): Estimated exposure by symbol.

        Example:
            result = service.verify_halt(
                scope=KillSwitchScope.GLOBAL,
                target_id="global"
            )
            # result["verified"] == True if halt is confirmed
        """
        ...
