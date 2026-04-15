"""
P&L attribution and performance tracking service.

Purpose:
    Calculate per-deployment P&L summary, timeseries, per-symbol attribution,
    strategy comparison, and persist daily snapshots.

Responsibilities:
    - Aggregate realized/unrealized P&L from positions.
    - Compute performance metrics: win rate, Sharpe ratio, max drawdown,
      profit factor from fill and order history.
    - Build P&L timeseries from persisted daily snapshots with daily change
      and drawdown calculations.
    - Produce per-symbol attribution with contribution percentages.
    - Compare multiple deployments on key metrics.
    - Persist daily P&L snapshots via the snapshot repository.

Does NOT:
    - Submit orders or manage broker connections.
    - Access the database directly (delegates to repository interfaces).
    - Know about HTTP, WebSocket, or transport concerns.

Dependencies:
    - DeploymentRepositoryInterface: verify deployment existence, get metadata.
    - PositionRepositoryInterface: current position state for P&L.
    - OrderFillRepositoryInterface: fill history for commission tracking.
    - OrderRepositoryInterface: order history for trade statistics.
    - PnlSnapshotRepositoryInterface: daily snapshot persistence and retrieval.

Error conditions:
    - NotFoundError: deployment does not exist.
    - ValidationError: invalid date range or empty comparison list.

Example:
    service = PnlAttributionService(
        deployment_repo=deployment_repo,
        position_repo=position_repo,
        order_fill_repo=order_fill_repo,
        order_repo=order_repo,
        pnl_snapshot_repo=pnl_snapshot_repo,
    )
    summary = service.get_pnl_summary(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.order_fill_repository_interface import (
    OrderFillRepositoryInterface,
)
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
)
from libs.contracts.interfaces.pnl_snapshot_repository_interface import (
    PnlSnapshotRepositoryInterface,
)
from libs.contracts.interfaces.position_repository_interface import (
    PositionRepositoryInterface,
)
from services.api.services.interfaces.pnl_attribution_service_interface import (
    PnlAttributionServiceInterface,
)

logger = structlog.get_logger(__name__)

# Annualization factor for Sharpe ratio (trading days)
_TRADING_DAYS_PER_YEAR = Decimal("252")


def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """
    Safely convert a value to Decimal.

    Handles string, int, float, and None inputs. Returns default on
    any conversion error.

    Args:
        value: Value to convert (string, int, float, Decimal, or None).
        default: Fallback value if conversion fails.

    Returns:
        Decimal representation of the value, or default.
    """
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


class PnlAttributionService(PnlAttributionServiceInterface):
    """
    Production P&L attribution and performance tracking service.

    Responsibilities:
    - Calculate aggregate P&L from positions and fills.
    - Compute performance metrics (win rate, Sharpe, max drawdown).
    - Build P&L timeseries with drawdown and daily change.
    - Produce per-symbol attribution with contribution percentages.
    - Compare deployments on key metrics.
    - Persist daily P&L snapshots.

    Does NOT:
    - Submit orders, manage broker connections, or handle transport.
    - Access storage directly (uses injected repository interfaces).

    Dependencies:
        deployment_repo: Verify deployment exists, get metadata.
        position_repo: Current position state for realized/unrealized P&L.
        order_fill_repo: Fill history for commission and volume tracking.
        order_repo: Order history for trade statistics.
        pnl_snapshot_repo: Daily snapshot persistence and retrieval.

    Example:
        service = PnlAttributionService(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=order_fill_repo,
            order_repo=order_repo,
            pnl_snapshot_repo=pnl_snapshot_repo,
        )
        summary = service.get_pnl_summary(deployment_id="01HDEPLOY...")
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        position_repo: PositionRepositoryInterface,
        order_fill_repo: OrderFillRepositoryInterface,
        order_repo: OrderRepositoryInterface,
        pnl_snapshot_repo: PnlSnapshotRepositoryInterface,
    ) -> None:
        self._deployment_repo = deployment_repo
        self._position_repo = position_repo
        self._order_fill_repo = order_fill_repo
        self._order_repo = order_repo
        self._pnl_snapshot_repo = pnl_snapshot_repo

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _verify_deployment(self, deployment_id: str) -> dict[str, Any]:
        """
        Verify deployment exists, raising NotFoundError if missing.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Deployment record dict.

        Raises:
            NotFoundError: If deployment does not exist.
        """
        record = self._deployment_repo.get_by_id(deployment_id)
        if record is None:
            raise NotFoundError(f"Deployment {deployment_id} does not exist")
        return record

    def _compute_trade_statistics(
        self,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Compute trade-level statistics from orders and fills.

        Pairs buy/sell fills per symbol to identify round-trip trades
        (a buy followed by a sell, or vice versa). Calculates win/loss
        counts and per-trade P&L for win rate, avg win, avg loss, and
        profit factor.

        This approach groups fills by symbol chronologically and pairs
        buys with sells using FIFO matching to determine per-trade P&L.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Dict with keys: total_trades, winning_trades, losing_trades,
            win_rate, avg_win, avg_loss, profit_factor, total_commission.
        """
        # Get all filled orders for this deployment
        all_orders = self._order_repo.list_by_deployment(
            deployment_id=deployment_id,
            status="filled",
        )

        # Get all fills for this deployment
        all_fills = self._order_fill_repo.list_by_deployment(
            deployment_id=deployment_id,
        )

        # Calculate total commission from fills
        total_commission = sum(_safe_decimal(f.get("commission", "0")) for f in all_fills)

        if not all_orders:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": Decimal("0"),
                "avg_win": None,
                "avg_loss": None,
                "profit_factor": None,
                "total_commission": total_commission,
            }

        # Group orders by symbol for FIFO trade matching
        symbol_orders: dict[str, list[dict[str, Any]]] = {}
        for order in all_orders:
            sym = order.get("symbol", "UNKNOWN")
            if sym not in symbol_orders:
                symbol_orders[sym] = []
            symbol_orders[sym].append(order)

        # FIFO trade matching: pair buys with sells
        trade_pnls: list[Decimal] = []
        for _sym, orders in symbol_orders.items():
            # Sort orders chronologically
            orders.sort(key=lambda o: o.get("created_at", ""))

            buy_queue: list[tuple[Decimal, Decimal]] = []  # (price, qty)
            for order in orders:
                side = order.get("side", "").lower()
                qty = _safe_decimal(order.get("filled_quantity", order.get("quantity", "0")))
                price = _safe_decimal(order.get("average_fill_price", "0"))

                if qty <= 0 or price <= 0:
                    continue

                if side == "buy":
                    buy_queue.append((price, qty))
                elif side == "sell" and buy_queue:
                    # Match against buy queue (FIFO)
                    remaining_sell = qty
                    while remaining_sell > 0 and buy_queue:
                        buy_price, buy_qty = buy_queue[0]
                        match_qty = min(remaining_sell, buy_qty)
                        pnl = (price - buy_price) * match_qty
                        trade_pnls.append(pnl)

                        remaining_sell -= match_qty
                        if match_qty >= buy_qty:
                            buy_queue.pop(0)
                        else:
                            buy_queue[0] = (buy_price, buy_qty - match_qty)

        # Compute statistics
        winning = [p for p in trade_pnls if p > 0]
        losing = [p for p in trade_pnls if p <= 0]

        total_trades = len(trade_pnls)
        winning_trades = len(winning)
        losing_trades = len(losing)

        win_rate = (
            Decimal(str(winning_trades)) / Decimal(str(total_trades)) * Decimal("100")
            if total_trades > 0
            else Decimal("0")
        )
        # Round to 1 decimal
        win_rate = win_rate.quantize(Decimal("0.1"))

        gross_profit = sum(winning, Decimal("0")) if winning else Decimal("0")
        gross_loss = abs(sum(losing, Decimal("0"))) if losing else Decimal("0")

        avg_win = gross_profit / Decimal(str(winning_trades)) if winning_trades > 0 else None
        avg_loss = gross_loss / Decimal(str(losing_trades)) if losing_trades > 0 else None

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "avg_win": str(avg_win.quantize(Decimal("0.01"))) if avg_win is not None else None,
            "avg_loss": str(avg_loss.quantize(Decimal("0.01"))) if avg_loss is not None else None,
            "profit_factor": (
                str(profit_factor.quantize(Decimal("0.01"))) if profit_factor is not None else None
            ),
            "total_commission": total_commission,
        }

    def _compute_sharpe_ratio(
        self,
        daily_returns: list[Decimal],
    ) -> Decimal | None:
        """
        Calculate annualized Sharpe ratio from daily returns.

        Uses the formula: Sharpe = (mean_return / std_return) * sqrt(252)
        where 252 is the number of trading days per year.

        Args:
            daily_returns: List of daily P&L changes as Decimal values.

        Returns:
            Annualized Sharpe ratio, or None if insufficient data (< 2 days)
            or zero standard deviation.
        """
        if len(daily_returns) < 2:
            return None

        n = Decimal(str(len(daily_returns)))
        mean_ret = sum(daily_returns) / n

        # Standard deviation
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (n - 1)
        if variance <= 0:
            return None

        # Use float for sqrt, then convert back
        std_ret = Decimal(str(math.sqrt(float(variance))))
        if std_ret == 0:
            return None

        sharpe = (mean_ret / std_ret) * Decimal(str(math.sqrt(float(_TRADING_DAYS_PER_YEAR))))
        return sharpe.quantize(Decimal("0.01"))

    def _compute_max_drawdown(
        self,
        cumulative_pnls: list[Decimal],
    ) -> Decimal | None:
        """
        Calculate maximum peak-to-trough drawdown percentage.

        Args:
            cumulative_pnls: List of cumulative P&L values in chronological order.

        Returns:
            Maximum drawdown as a percentage (e.g., 12.5 means 12.5%),
            or None if insufficient data or no positive peak.
        """
        if len(cumulative_pnls) < 2:
            return None

        peak = cumulative_pnls[0]
        max_dd = Decimal("0")

        for pnl in cumulative_pnls:
            if pnl > peak:
                peak = pnl
            if peak > 0:
                dd = (peak - pnl) / peak * Decimal("100")
                if dd > max_dd:
                    max_dd = dd

        return max_dd.quantize(Decimal("0.1")) if max_dd > 0 else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_pnl_summary(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Compute current P&L summary for a deployment.

        Aggregates realized/unrealized P&L from positions, commissions from
        fills, and computes trade-level metrics (win rate, Sharpe ratio,
        max drawdown) from order history.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Dict matching PnlSummary schema with all performance metrics.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        self._verify_deployment(deployment_id)

        logger.info(
            "pnl_attribution.summary_started",
            deployment_id=deployment_id,
            component="pnl_attribution_service",
        )

        # Aggregate from positions
        positions = self._position_repo.list_by_deployment(
            deployment_id=deployment_id,
        )

        total_realized = Decimal("0")
        total_unrealized = Decimal("0")

        for pos in positions:
            total_realized += _safe_decimal(pos.get("realized_pnl", "0"))
            total_unrealized += _safe_decimal(pos.get("unrealized_pnl", "0"))

        # Compute trade stats
        trade_stats = self._compute_trade_statistics(deployment_id)
        total_commission = trade_stats["total_commission"]
        total_fees = Decimal("0")  # Fees tracked separately if exchange provides

        net_pnl = total_realized + total_unrealized - total_commission - total_fees

        # Compute Sharpe and drawdown from snapshots if available
        snapshots = self._pnl_snapshot_repo.list_by_deployment(
            deployment_id=deployment_id,
            date_from=date(2020, 1, 1),  # Far past to get all
            date_to=date(2099, 12, 31),  # Far future to get all
        )

        daily_returns: list[Decimal] = []
        cumulative_pnls: list[Decimal] = []
        prev_net = Decimal("0")

        for snap in snapshots:
            snap_net = _safe_decimal(snap.get("realized_pnl", "0")) + _safe_decimal(
                snap.get("unrealized_pnl", "0")
            )
            daily_returns.append(snap_net - prev_net)
            cumulative_pnls.append(snap_net)
            prev_net = snap_net

        sharpe_ratio = self._compute_sharpe_ratio(daily_returns)
        max_drawdown = self._compute_max_drawdown(cumulative_pnls)

        # Determine date range from snapshots
        date_from = snapshots[0]["snapshot_date"] if snapshots else None
        date_to = snapshots[-1]["snapshot_date"] if snapshots else None

        result = {
            "deployment_id": deployment_id,
            "total_realized_pnl": str(total_realized),
            "total_unrealized_pnl": str(total_unrealized),
            "total_commission": str(total_commission),
            "total_fees": str(total_fees),
            "net_pnl": str(net_pnl),
            "positions_count": len(positions),
            "total_trades": trade_stats["total_trades"],
            "winning_trades": trade_stats["winning_trades"],
            "losing_trades": trade_stats["losing_trades"],
            "win_rate": str(trade_stats["win_rate"]),
            "sharpe_ratio": str(sharpe_ratio) if sharpe_ratio is not None else None,
            "max_drawdown_pct": str(max_drawdown) if max_drawdown is not None else None,
            "avg_win": trade_stats["avg_win"],
            "avg_loss": trade_stats["avg_loss"],
            "profit_factor": trade_stats["profit_factor"],
            "date_from": date_from,
            "date_to": date_to,
        }

        logger.info(
            "pnl_attribution.summary_completed",
            deployment_id=deployment_id,
            net_pnl=str(net_pnl),
            positions_count=len(positions),
            total_trades=trade_stats["total_trades"],
            component="pnl_attribution_service",
        )

        return result

    def get_pnl_timeseries(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
        granularity: str = "daily",
    ) -> list[dict[str, Any]]:
        """
        Retrieve P&L timeseries from daily snapshots.

        Builds timeseries points with cumulative P&L, daily change, and
        drawdown percentage from persisted snapshots. Supports daily,
        weekly, and monthly granularity.

        Args:
            deployment_id: Deployment ULID.
            date_from: Inclusive start date.
            date_to: Inclusive end date.
            granularity: "daily", "weekly", or "monthly".

        Returns:
            List of dicts matching PnlTimeseriesPoint schema.

        Raises:
            NotFoundError: If deployment does not exist.
            ValidationError: If date_from > date_to or invalid granularity.
        """
        self._verify_deployment(deployment_id)

        if date_from > date_to:
            raise ValidationError("date_from must be <= date_to")
        if granularity not in ("daily", "weekly", "monthly"):
            raise ValidationError(
                f"Invalid granularity: {granularity}. Must be daily, weekly, or monthly."
            )

        logger.info(
            "pnl_attribution.timeseries_started",
            deployment_id=deployment_id,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            granularity=granularity,
            component="pnl_attribution_service",
        )

        snapshots = self._pnl_snapshot_repo.list_by_deployment(
            deployment_id=deployment_id,
            date_from=date_from,
            date_to=date_to,
        )

        if not snapshots:
            return []

        # Build timeseries with daily change and drawdown
        points: list[dict[str, Any]] = []
        prev_net = Decimal("0")
        peak_net = Decimal("0")

        for snap in snapshots:
            realized = _safe_decimal(snap.get("realized_pnl", "0"))
            unrealized = _safe_decimal(snap.get("unrealized_pnl", "0"))
            net = realized + unrealized
            commission = _safe_decimal(snap.get("commission", "0"))
            fees = _safe_decimal(snap.get("fees", "0"))

            daily_change = net - prev_net
            cumulative = net

            # Track peak and drawdown
            if net > peak_net:
                peak_net = net
            drawdown_pct = Decimal("0")
            if peak_net > 0:
                drawdown_pct = ((peak_net - net) / peak_net * Decimal("100")).quantize(
                    Decimal("0.01")
                )

            point = {
                "snapshot_date": snap["snapshot_date"],
                "realized_pnl": str(realized),
                "unrealized_pnl": str(unrealized),
                "net_pnl": str(net),
                "cumulative_pnl": str(cumulative),
                "daily_pnl": str(daily_change),
                "commission": str(commission),
                "fees": str(fees),
                "positions_count": snap.get("positions_count", 0),
                "drawdown_pct": str(drawdown_pct),
            }
            points.append(point)
            prev_net = net

        # Aggregate for weekly/monthly if needed
        if granularity != "daily":
            points = self._aggregate_timeseries(points, granularity)

        logger.info(
            "pnl_attribution.timeseries_completed",
            deployment_id=deployment_id,
            points_count=len(points),
            component="pnl_attribution_service",
        )

        return points

    def _aggregate_timeseries(
        self,
        points: list[dict[str, Any]],
        granularity: str,
    ) -> list[dict[str, Any]]:
        """
        Aggregate daily timeseries points to weekly or monthly granularity.

        Groups daily points by week (ISO week) or month, taking the last
        point in each period as the period's representative value.

        Args:
            points: Daily timeseries points.
            granularity: "weekly" or "monthly".

        Returns:
            Aggregated timeseries points with one per period.
        """
        if not points:
            return []

        grouped: dict[str, list[dict[str, Any]]] = {}

        for point in points:
            snap_date = date.fromisoformat(point["snapshot_date"])

            if granularity == "weekly":
                # ISO year-week as group key
                iso_year, iso_week, _ = snap_date.isocalendar()
                key = f"{iso_year}-W{iso_week:02d}"
            else:  # monthly
                key = f"{snap_date.year}-{snap_date.month:02d}"

            if key not in grouped:
                grouped[key] = []
            grouped[key].append(point)

        # Take the last point in each period (end-of-period snapshot)
        aggregated = []
        for period_points in grouped.values():
            aggregated.append(period_points[-1])

        return aggregated

    def get_attribution(
        self,
        *,
        deployment_id: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """
        Compute per-symbol P&L attribution for a deployment.

        Breaks down the deployment's total P&L by symbol, calculating each
        symbol's realized/unrealized P&L and its percentage contribution to
        the total.

        Args:
            deployment_id: Deployment ULID.
            date_from: Optional filter start date (not yet used — reserved).
            date_to: Optional filter end date (not yet used — reserved).

        Returns:
            Dict matching PnlAttributionReport schema.

        Raises:
            NotFoundError: If deployment does not exist.
        """
        self._verify_deployment(deployment_id)

        logger.info(
            "pnl_attribution.attribution_started",
            deployment_id=deployment_id,
            component="pnl_attribution_service",
        )

        positions = self._position_repo.list_by_deployment(
            deployment_id=deployment_id,
        )

        # Get fills for volume and commission tracking
        all_fills = self._order_fill_repo.list_by_deployment(
            deployment_id=deployment_id,
        )

        # Build fill-level data by order, then map to symbol via orders
        order_cache: dict[str, dict[str, Any]] = {}
        symbol_fills: dict[str, list[dict[str, Any]]] = {}

        for fill in all_fills:
            order_id = fill.get("order_id", "")
            if order_id not in order_cache:
                try:
                    order_cache[order_id] = self._order_repo.get_by_id(order_id)
                except Exception:
                    continue
            order = order_cache[order_id]
            sym = order.get("symbol", "UNKNOWN")
            if sym not in symbol_fills:
                symbol_fills[sym] = []
            symbol_fills[sym].append(fill)

        # Build per-symbol attribution from positions
        total_net_pnl = Decimal("0")
        by_symbol: list[dict[str, Any]] = []

        for pos in positions:
            sym = pos.get("symbol", "UNKNOWN")
            realized = _safe_decimal(pos.get("realized_pnl", "0"))
            unrealized = _safe_decimal(pos.get("unrealized_pnl", "0"))
            net = realized + unrealized
            total_net_pnl += net

            # Get fills for this symbol for commission and volume
            fills = symbol_fills.get(sym, [])
            commission = sum(_safe_decimal(f.get("commission", "0")) for f in fills)
            volume = sum(_safe_decimal(f.get("quantity", "0")) for f in fills)

            by_symbol.append(
                {
                    "symbol": sym,
                    "realized_pnl": str(realized),
                    "unrealized_pnl": str(unrealized),
                    "net_pnl": str(net),
                    "contribution_pct": "0",  # Computed below
                    "total_trades": 0,  # Simplified — could be enhanced with order count
                    "winning_trades": 0,
                    "win_rate": "0",
                    "total_volume": str(volume),
                    "commission": str(commission),
                }
            )

        # Compute contribution percentages
        if total_net_pnl != 0:
            for entry in by_symbol:
                entry_net = _safe_decimal(entry["net_pnl"])
                contribution = (entry_net / total_net_pnl * Decimal("100")).quantize(Decimal("0.1"))
                entry["contribution_pct"] = str(contribution)

        result = {
            "deployment_id": deployment_id,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "total_net_pnl": str(total_net_pnl),
            "by_symbol": by_symbol,
        }

        logger.info(
            "pnl_attribution.attribution_completed",
            deployment_id=deployment_id,
            total_net_pnl=str(total_net_pnl),
            symbols_count=len(by_symbol),
            component="pnl_attribution_service",
        )

        return result

    def get_comparison(
        self,
        *,
        deployment_ids: list[str],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """
        Compare P&L metrics across multiple deployments.

        Produces one entry per deployment with key performance metrics for
        side-by-side comparison. Skips deployments that do not exist (logs
        warning instead of raising).

        Args:
            deployment_ids: List of deployment ULIDs to compare.
            date_from: Optional comparison start date.
            date_to: Optional comparison end date.

        Returns:
            Dict matching PnlComparisonReport schema.

        Raises:
            ValidationError: If deployment_ids is empty.
        """
        if not deployment_ids:
            raise ValidationError("deployment_ids must not be empty")

        logger.info(
            "pnl_attribution.comparison_started",
            deployment_count=len(deployment_ids),
            component="pnl_attribution_service",
        )

        entries: list[dict[str, Any]] = []

        for deploy_id in deployment_ids:
            deployment = self._deployment_repo.get_by_id(deploy_id)
            if deployment is None:
                logger.warning(
                    "pnl_attribution.comparison_deployment_not_found",
                    deployment_id=deploy_id,
                    component="pnl_attribution_service",
                )
                continue

            # Get summary for this deployment
            try:
                summary = self.get_pnl_summary(deployment_id=deploy_id)
            except NotFoundError:
                continue

            entry = {
                "deployment_id": deploy_id,
                "strategy_name": deployment.get("strategy_id"),  # Could be enhanced
                "net_pnl": summary["net_pnl"],
                "total_realized_pnl": summary["total_realized_pnl"],
                "total_unrealized_pnl": summary["total_unrealized_pnl"],
                "total_commission": summary["total_commission"],
                "win_rate": summary["win_rate"],
                "sharpe_ratio": summary.get("sharpe_ratio"),
                "max_drawdown_pct": summary.get("max_drawdown_pct"),
                "total_trades": summary["total_trades"],
            }
            entries.append(entry)

        result = {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "entries": entries,
        }

        logger.info(
            "pnl_attribution.comparison_completed",
            entries_count=len(entries),
            component="pnl_attribution_service",
        )

        return result

    def take_snapshot(
        self,
        *,
        deployment_id: str,
        snapshot_date: date,
    ) -> dict[str, Any]:
        """
        Persist a daily P&L snapshot for a deployment.

        Reads current position state, aggregates realized/unrealized P&L,
        and persists as a snapshot record. Uses upsert semantics — calling
        this twice for the same date updates the existing record.

        Args:
            deployment_id: Deployment ULID.
            snapshot_date: Date to record the snapshot for.

        Returns:
            Dict with the persisted snapshot record.

        Raises:
            NotFoundError: If the deployment does not exist.
        """
        self._verify_deployment(deployment_id)

        logger.info(
            "pnl_attribution.snapshot_started",
            deployment_id=deployment_id,
            snapshot_date=snapshot_date.isoformat(),
            component="pnl_attribution_service",
        )

        # Aggregate from current positions
        positions = self._position_repo.list_by_deployment(
            deployment_id=deployment_id,
        )

        total_realized = Decimal("0")
        total_unrealized = Decimal("0")

        for pos in positions:
            total_realized += _safe_decimal(pos.get("realized_pnl", "0"))
            total_unrealized += _safe_decimal(pos.get("unrealized_pnl", "0"))

        # Commission from fills
        fills = self._order_fill_repo.list_by_deployment(
            deployment_id=deployment_id,
        )
        total_commission = sum(_safe_decimal(f.get("commission", "0")) for f in fills)

        result = self._pnl_snapshot_repo.save(
            deployment_id=deployment_id,
            snapshot_date=snapshot_date,
            realized_pnl=str(total_realized),
            unrealized_pnl=str(total_unrealized),
            commission=str(total_commission),
            fees="0",
            positions_count=len(positions),
        )

        logger.info(
            "pnl_attribution.snapshot_completed",
            deployment_id=deployment_id,
            snapshot_date=snapshot_date.isoformat(),
            realized_pnl=str(total_realized),
            unrealized_pnl=str(total_unrealized),
            positions_count=len(positions),
            component="pnl_attribution_service",
        )

        return result
