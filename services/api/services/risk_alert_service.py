"""
Risk alert evaluation service (Phase 7 — M11).

Responsibilities:
- Evaluate portfolio risk metrics against configured thresholds.
- Create incidents via IncidentManager when thresholds are breached.
- Manage alert configurations per deployment (CRUD).
- Provide default configuration when none is explicitly set.

Does NOT:
- Compute risk metrics directly (delegates to RiskAnalyticsServiceInterface).
- Deliver notifications (delegates to IncidentManager).
- Schedule evaluation runs (caller / task scheduler responsibility).

Dependencies:
- RiskAnalyticsServiceInterface (injected): Computes VaR, correlation, concentration.
- RiskAlertConfigRepositoryInterface (injected): Persists alert configurations.
- IncidentManager (injected, optional): Dispatches alerts. None in read-only mode.

Error conditions:
- NotFoundError: no positions for deployment (from risk analytics service).
- ValidationError: invalid configuration values.

Example:
    service = RiskAlertService(
        risk_analytics=analytics_service,
        config_repo=config_repo,
        incident_manager=incident_manager,
    )
    result = service.evaluate_alerts("01HTESTDEPLOY000000000000")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from libs.contracts.interfaces.risk_alert_config_repository import (
    RiskAlertConfigRepositoryInterface,
)
from libs.contracts.interfaces.risk_alert_service import RiskAlertServiceInterface
from libs.contracts.interfaces.risk_analytics_service import (
    RiskAnalyticsServiceInterface,
)
from libs.contracts.notification import AlertTriggerType
from libs.contracts.risk_alert import (
    RiskAlert,
    RiskAlertConfig,
    RiskAlertEvaluation,
    RiskAlertType,
)
from services.api.infrastructure.incident_manager import IncidentManager

logger = logging.getLogger(__name__)

# Default thresholds used when no config exists for a deployment
_DEFAULT_VAR_THRESHOLD = Decimal("5.0")
_DEFAULT_CONCENTRATION_THRESHOLD = Decimal("30.0")
_DEFAULT_CORRELATION_THRESHOLD = Decimal("0.90")
_DEFAULT_LOOKBACK_DAYS = 252


class RiskAlertService(RiskAlertServiceInterface):
    """
    Production implementation of risk alert evaluation.

    Evaluates three risk dimensions against configurable thresholds:
    1. VaR breach: portfolio VaR 95% exceeds threshold percentage of equity.
    2. Concentration breach: single position exceeds threshold percentage.
    3. Correlation spike: pairwise correlation exceeds threshold.

    When a breach is detected, creates an incident via IncidentManager
    for notification dispatch (Slack, PagerDuty, etc.).

    Responsibilities:
    - Evaluate risk metrics against thresholds.
    - Create incidents for breaches.
    - CRUD for alert configurations.

    Does NOT:
    - Compute metrics directly (delegates to RiskAnalyticsServiceInterface).
    - Deliver notifications (delegates to IncidentManager).

    Example:
        service = RiskAlertService(
            risk_analytics=analytics_service,
            config_repo=config_repo,
            incident_manager=incident_manager,
        )
        result = service.evaluate_alerts("01H...")
    """

    def __init__(
        self,
        *,
        risk_analytics: RiskAnalyticsServiceInterface,
        config_repo: RiskAlertConfigRepositoryInterface,
        incident_manager: IncidentManager | None = None,
    ) -> None:
        """
        Initialize the risk alert service.

        Args:
            risk_analytics: Service for computing VaR, correlation, concentration.
            config_repo: Repository for persisting alert configurations.
            incident_manager: IncidentManager for dispatching alerts. None disables dispatch.
        """
        self._analytics = risk_analytics
        self._config_repo = config_repo
        self._incident_manager = incident_manager

    def evaluate_alerts(self, deployment_id: str) -> RiskAlertEvaluation:
        """
        Evaluate all risk alert rules for a deployment.

        Fetches the alert configuration (or defaults), computes current
        risk metrics, and compares against thresholds. Any breaches are
        dispatched as incidents via IncidentManager.

        Args:
            deployment_id: Target deployment to evaluate.

        Returns:
            RiskAlertEvaluation with list of triggered alerts.

        Raises:
            NotFoundError: If the deployment has no positions.
        """
        config = self._get_effective_config(deployment_id)
        alerts: list[RiskAlert] = []
        rules_checked = 0

        logger.info(
            "Evaluating risk alerts",
            extra={
                "operation": "evaluate_alerts",
                "component": "RiskAlertService",
                "deployment_id": deployment_id,
                "enabled": config.enabled,
            },
        )

        if not config.enabled:
            return RiskAlertEvaluation(
                deployment_id=deployment_id,
                alerts_triggered=[],
                total_rules_checked=0,
                evaluated_at=datetime.now(timezone.utc),
            )

        # --- Rule 1: VaR threshold breach ---
        rules_checked += 1
        try:
            var_result = self._analytics.compute_var(
                deployment_id=deployment_id,
                lookback_days=config.lookback_days,
            )
            # VaR is expressed as a percentage of portfolio value
            # var_95 from the analytics service is already a decimal dollar value
            # We need to compare against the threshold as a percentage
            # The analytics service returns absolute VaR, so we need portfolio value
            summary = self._analytics.get_portfolio_risk_summary(
                deployment_id=deployment_id,
                lookback_days=config.lookback_days,
            )
            total_exposure = summary.gross_exposure
            if total_exposure > 0:
                var_pct = (abs(var_result.var_95) / total_exposure * 100).quantize(Decimal("0.01"))
                if var_pct > config.var_threshold_pct:
                    alert = RiskAlert(
                        alert_type=RiskAlertType.VAR_BREACH,
                        message=(
                            f"VaR 95% ({var_pct}%) exceeds threshold "
                            f"({config.var_threshold_pct}%) for deployment {deployment_id}"
                        ),
                        current_value=var_pct,
                        threshold_value=config.var_threshold_pct,
                    )
                    alerts.append(alert)
                    self._dispatch_alert(
                        deployment_id=deployment_id,
                        trigger_type=AlertTriggerType.VAR_THRESHOLD_BREACH,
                        title=f"VaR threshold breach: {var_pct}% > {config.var_threshold_pct}%",
                        details={
                            "var_95_pct": str(var_pct),
                            "threshold_pct": str(config.var_threshold_pct),
                            "var_95_value": str(var_result.var_95),
                            "gross_exposure": str(total_exposure),
                        },
                    )
        except Exception as exc:
            logger.warning(
                "VaR evaluation failed",
                extra={
                    "operation": "evaluate_alerts",
                    "component": "RiskAlertService",
                    "deployment_id": deployment_id,
                    "error": str(exc),
                },
            )

        # --- Rule 2: Concentration threshold breach ---
        rules_checked += 1
        try:
            concentration = self._analytics.compute_concentration(
                deployment_id=deployment_id,
            )
            for entry in concentration.per_symbol:
                if entry.pct_of_portfolio > config.concentration_threshold_pct:
                    alert = RiskAlert(
                        alert_type=RiskAlertType.CONCENTRATION_BREACH,
                        message=(
                            f"{entry.symbol} concentration ({entry.pct_of_portfolio}%) "
                            f"exceeds threshold ({config.concentration_threshold_pct}%)"
                        ),
                        current_value=entry.pct_of_portfolio,
                        threshold_value=config.concentration_threshold_pct,
                        symbol=entry.symbol,
                    )
                    alerts.append(alert)
                    self._dispatch_alert(
                        deployment_id=deployment_id,
                        trigger_type=AlertTriggerType.CONCENTRATION_THRESHOLD_BREACH,
                        title=(
                            f"Concentration breach: {entry.symbol} at {entry.pct_of_portfolio}%"
                        ),
                        details={
                            "symbol": entry.symbol,
                            "pct_of_portfolio": str(entry.pct_of_portfolio),
                            "threshold_pct": str(config.concentration_threshold_pct),
                            "market_value": str(entry.market_value),
                        },
                    )
        except Exception as exc:
            logger.warning(
                "Concentration evaluation failed",
                extra={
                    "operation": "evaluate_alerts",
                    "component": "RiskAlertService",
                    "deployment_id": deployment_id,
                    "error": str(exc),
                },
            )

        # --- Rule 3: Correlation spike ---
        rules_checked += 1
        try:
            corr_matrix = self._analytics.compute_correlation_matrix(
                deployment_id=deployment_id,
                lookback_days=config.lookback_days,
            )
            # Check all pairwise correlations (avoid self-correlation diagonal)
            seen_pairs: set[tuple[str, str]] = set()
            for corr_entry in corr_matrix.entries:
                if corr_entry.symbol_a == corr_entry.symbol_b:
                    continue
                # Normalize pair order to avoid duplicate alerts
                pair = tuple(sorted([corr_entry.symbol_a, corr_entry.symbol_b]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)  # type: ignore[arg-type]

                if corr_entry.correlation > config.correlation_threshold:
                    alert = RiskAlert(
                        alert_type=RiskAlertType.CORRELATION_SPIKE,
                        message=(
                            f"Correlation between {corr_entry.symbol_a} and {corr_entry.symbol_b} "
                            f"({corr_entry.correlation}) exceeds threshold "
                            f"({config.correlation_threshold})"
                        ),
                        current_value=corr_entry.correlation,
                        threshold_value=config.correlation_threshold,
                        symbol=corr_entry.symbol_a,
                        symbol_b=corr_entry.symbol_b,
                    )
                    alerts.append(alert)
                    self._dispatch_alert(
                        deployment_id=deployment_id,
                        trigger_type=AlertTriggerType.CORRELATION_SPIKE,
                        title=(
                            f"Correlation spike: {corr_entry.symbol_a}/{corr_entry.symbol_b} "
                            f"= {corr_entry.correlation}"
                        ),
                        details={
                            "symbol_a": corr_entry.symbol_a,
                            "symbol_b": corr_entry.symbol_b,
                            "correlation": str(corr_entry.correlation),
                            "threshold": str(config.correlation_threshold),
                        },
                    )
        except Exception as exc:
            logger.warning(
                "Correlation evaluation failed",
                extra={
                    "operation": "evaluate_alerts",
                    "component": "RiskAlertService",
                    "deployment_id": deployment_id,
                    "error": str(exc),
                },
            )

        evaluation = RiskAlertEvaluation(
            deployment_id=deployment_id,
            alerts_triggered=alerts,
            total_rules_checked=rules_checked,
            evaluated_at=datetime.now(timezone.utc),
        )

        logger.info(
            "Risk alert evaluation complete",
            extra={
                "operation": "evaluate_alerts",
                "component": "RiskAlertService",
                "deployment_id": deployment_id,
                "alerts_triggered": len(alerts),
                "rules_checked": rules_checked,
            },
        )

        return evaluation

    def get_config(self, deployment_id: str) -> RiskAlertConfig:
        """
        Get the alert configuration for a deployment.

        Returns the persisted config or a default config if none exists.

        Args:
            deployment_id: Target deployment.

        Returns:
            RiskAlertConfig for the deployment.
        """
        return self._get_effective_config(deployment_id)

    def update_config(self, config: RiskAlertConfig) -> RiskAlertConfig:
        """
        Create or update the alert configuration for a deployment.

        Args:
            config: New alert configuration.

        Returns:
            The saved RiskAlertConfig.
        """
        saved = self._config_repo.save(config)

        logger.info(
            "Risk alert config updated",
            extra={
                "operation": "update_config",
                "component": "RiskAlertService",
                "deployment_id": config.deployment_id,
                "enabled": config.enabled,
            },
        )

        return saved

    def list_configs(self) -> list[RiskAlertConfig]:
        """
        List all alert configurations.

        Returns:
            List of all configured RiskAlertConfig entries.
        """
        return self._config_repo.find_all()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_effective_config(self, deployment_id: str) -> RiskAlertConfig:
        """
        Get persisted config or default for a deployment.

        Args:
            deployment_id: Target deployment.

        Returns:
            Persisted config or default RiskAlertConfig.
        """
        config = self._config_repo.find_by_deployment_id(deployment_id)
        if config is not None:
            return config
        # Return default config (not persisted until explicitly saved)
        return RiskAlertConfig(
            deployment_id=deployment_id,
            var_threshold_pct=_DEFAULT_VAR_THRESHOLD,
            concentration_threshold_pct=_DEFAULT_CONCENTRATION_THRESHOLD,
            correlation_threshold=_DEFAULT_CORRELATION_THRESHOLD,
            lookback_days=_DEFAULT_LOOKBACK_DAYS,
        )

    def _dispatch_alert(
        self,
        *,
        deployment_id: str,
        trigger_type: AlertTriggerType,
        title: str,
        details: dict,
    ) -> None:
        """
        Dispatch an alert via IncidentManager if available.

        Failures are logged but never raised — alert dispatch must not
        prevent the evaluation from completing.

        Args:
            deployment_id: Affected deployment.
            trigger_type: Alert trigger type for incident routing.
            title: Short alert title.
            details: Structured alert details.
        """
        if self._incident_manager is None:
            logger.debug(
                "Alert dispatch skipped (no incident manager)",
                extra={
                    "operation": "dispatch_alert",
                    "component": "RiskAlertService",
                    "deployment_id": deployment_id,
                    "trigger_type": trigger_type.value,
                },
            )
            return

        try:
            self._incident_manager.create_incident(
                trigger_type=trigger_type,
                title=title,
                details={**details, "deployment_id": deployment_id},
                affected_services=["risk-analytics"],
            )
        except Exception as exc:
            logger.error(
                "Alert dispatch failed",
                extra={
                    "operation": "dispatch_alert",
                    "component": "RiskAlertService",
                    "deployment_id": deployment_id,
                    "trigger_type": trigger_type.value,
                    "error": str(exc),
                },
                exc_info=True,
            )
