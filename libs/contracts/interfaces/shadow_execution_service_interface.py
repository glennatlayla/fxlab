"""
Shadow execution service interface (port).

Responsibilities:
- Define the abstract contract for shadow-mode order execution.
- Shadow mode records what the system *would* have done without touching
  a real broker — orders are "filled" instantly at market price by the
  ShadowBrokerAdapter and the decision trail is persisted for analysis.

Does NOT:
- Execute real broker operations.
- Contain risk gate logic (delegated to a risk gate interface in M5).
- Know about specific broker APIs.

Dependencies:
- libs.contracts.execution: OrderRequest, OrderResponse, PositionSnapshot,
  AccountSnapshot.

Error conditions:
- NotFoundError: deployment_id does not exist.
- StateTransitionError: deployment is not in an executable shadow state.
- ValidationError: order request fails pre-trade validation.

Example:
    service: ShadowExecutionServiceInterface = ShadowExecutionService(...)
    resp = service.execute_shadow_order(
        deployment_id="01HDEPLOY...",
        request=order_request,
        correlation_id="corr-001",
    )
    decisions = service.get_shadow_decisions(deployment_id="01HDEPLOY...")
    pnl = service.get_shadow_pnl(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    OrderResponse,
    PositionSnapshot,
)


class ShadowExecutionServiceInterface(ABC):
    """
    Port interface for shadow-mode execution orchestration.

    Shadow execution follows the same signal → risk check → fill → audit
    pipeline as paper/live, but routes to a ShadowBrokerAdapter that logs
    decisions without real execution.

    Each deployment gets its own isolated shadow adapter instance, ensuring
    position tracking and P&L are per-deployment.

    Implementations:
    - ShadowExecutionService — production implementation (M3)

    Thread safety:
    - Implementations must be safe for concurrent calls across different
      deployment_ids. Concurrent calls for the *same* deployment_id are
      serialised by the caller (realtime worker).
    """

    @abstractmethod
    def execute_shadow_order(
        self,
        *,
        deployment_id: str,
        request: OrderRequest,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Execute a shadow order for a deployment.

        Pipeline: validate deployment → pre-trade risk check → shadow fill
        → record order event → return response.

        Args:
            deployment_id: ULID of the deployment in shadow mode.
            request: Normalized order submission payload.
            correlation_id: Distributed tracing ID from the originating signal.

        Returns:
            OrderResponse with FILLED status and shadow fill price.

        Raises:
            NotFoundError: deployment_id does not exist.
            StateTransitionError: deployment is not in an executable state
                (must be 'active' with execution_mode='shadow').
            ValidationError: order request fails pre-trade validation.

        Example:
            resp = service.execute_shadow_order(
                deployment_id="01HDEPLOY...",
                request=order_request,
                correlation_id="corr-001",
            )
            assert resp.status == OrderStatus.FILLED
            assert resp.execution_mode == ExecutionMode.SHADOW
        """
        ...

    @abstractmethod
    def update_market_price(
        self,
        *,
        deployment_id: str,
        symbol: str,
        price: Decimal,
    ) -> None:
        """
        Update the market price for a symbol within a deployment's shadow adapter.

        Called by the market data feed to keep shadow fills and P&L accurate.

        Args:
            deployment_id: ULID of the deployment.
            symbol: Instrument ticker.
            price: Current market price.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.

        Example:
            service.update_market_price(
                deployment_id="01HDEPLOY...",
                symbol="AAPL",
                price=Decimal("180.00"),
            )
        """
        ...

    @abstractmethod
    def get_shadow_decisions(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        Retrieve the full decision timeline for a shadow deployment.

        Each entry records an event (submitted, filled) with timestamp,
        correlation_id, symbol, side, quantity, and fill price.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of decision event dicts, ordered chronologically.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.

        Example:
            decisions = service.get_shadow_decisions(deployment_id="01HDEPLOY...")
            # [{"event_type": "shadow_order_submitted", ...}, ...]
        """
        ...

    @abstractmethod
    def get_shadow_pnl(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Get hypothetical P&L summary for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Dict with keys: total_unrealized_pnl, total_realized_pnl,
            positions (list of per-symbol P&L).

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.

        Example:
            pnl = service.get_shadow_pnl(deployment_id="01HDEPLOY...")
            # {"total_unrealized_pnl": "450.00", "total_realized_pnl": "0", ...}
        """
        ...

    @abstractmethod
    def get_shadow_positions(
        self,
        *,
        deployment_id: str,
    ) -> list[PositionSnapshot]:
        """
        Get current hypothetical positions for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of PositionSnapshot for non-zero positions.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.

        Example:
            positions = service.get_shadow_positions(deployment_id="01HDEPLOY...")
        """
        ...

    @abstractmethod
    def get_shadow_account(
        self,
        *,
        deployment_id: str,
    ) -> AccountSnapshot:
        """
        Get hypothetical account state for a shadow deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            AccountSnapshot with equity reflecting unrealized P&L.

        Raises:
            NotFoundError: deployment_id has no active shadow adapter.

        Example:
            acct = service.get_shadow_account(deployment_id="01HDEPLOY...")
            # acct.equity == initial_equity + unrealized_pnl
        """
        ...

    @abstractmethod
    def register_deployment(
        self,
        *,
        deployment_id: str,
        initial_equity: Decimal,
        market_prices: dict[str, Decimal] | None = None,
    ) -> None:
        """
        Register a deployment for shadow execution.

        Creates an isolated ShadowBrokerAdapter instance for the deployment.
        Must be called before any orders can be executed.

        Args:
            deployment_id: ULID of the deployment.
            initial_equity: Starting hypothetical equity.
            market_prices: Optional initial market price map.

        Raises:
            ValidationError: deployment_id is already registered.

        Example:
            service.register_deployment(
                deployment_id="01HDEPLOY...",
                initial_equity=Decimal("1000000"),
                market_prices={"AAPL": Decimal("175.50")},
            )
        """
        ...

    @abstractmethod
    def deregister_deployment(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """
        Deregister a deployment and clean up its shadow adapter.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment_id is not registered.

        Example:
            service.deregister_deployment(deployment_id="01HDEPLOY...")
        """
        ...
