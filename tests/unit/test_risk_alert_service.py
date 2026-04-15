"""
Unit tests for RiskAlertService.

Validates alert evaluation logic: VaR threshold breach detection,
concentration threshold breach detection, correlation spike detection,
configuration management, and IncidentManager dispatch integration.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from libs.contracts.mocks.mock_risk_alert_config_repository import (
    MockRiskAlertConfigRepository,
)
from libs.contracts.notification import AlertTriggerType
from libs.contracts.risk_alert import RiskAlertConfig, RiskAlertType
from libs.contracts.risk_analytics import (
    ConcentrationReport,
    CorrelationEntry,
    CorrelationMatrix,
    PortfolioRiskSummary,
    SymbolConcentration,
    VaRResult,
)
from services.api.services.risk_alert_service import RiskAlertService

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
_DEPLOY_ID = "01HTESTDEPLOY000000000000"


# ---------------------------------------------------------------------------
# Mock risk analytics service
# ---------------------------------------------------------------------------


class MockRiskAnalyticsService:
    """Mock that returns configurable risk metrics."""

    def __init__(self) -> None:
        self._var_result: VaRResult | None = None
        self._correlation_matrix: CorrelationMatrix | None = None
        self._concentration: ConcentrationReport | None = None
        self._summary: PortfolioRiskSummary | None = None
        self._raise_on_var: Exception | None = None
        self._raise_on_concentration: Exception | None = None
        self._raise_on_correlation: Exception | None = None

    def set_var_result(self, result: VaRResult) -> None:
        self._var_result = result

    def set_correlation_matrix(self, matrix: CorrelationMatrix) -> None:
        self._correlation_matrix = matrix

    def set_concentration(self, report: ConcentrationReport) -> None:
        self._concentration = report

    def set_summary(self, summary: PortfolioRiskSummary) -> None:
        self._summary = summary

    def set_raise_on_var(self, exc: Exception) -> None:
        self._raise_on_var = exc

    def set_raise_on_concentration(self, exc: Exception) -> None:
        self._raise_on_concentration = exc

    def set_raise_on_correlation(self, exc: Exception) -> None:
        self._raise_on_correlation = exc

    def compute_var(self, deployment_id: str, lookback_days: int = 252) -> VaRResult:
        if self._raise_on_var:
            raise self._raise_on_var
        return self._var_result or VaRResult(
            var_95=Decimal("2000.00"),
            var_99=Decimal("3000.00"),
            cvar_95=Decimal("2500.00"),
            cvar_99=Decimal("3500.00"),
            method="historical",
            lookback_days=lookback_days,
            computed_at=_NOW,
        )

    def compute_correlation_matrix(
        self, deployment_id: str, lookback_days: int = 252
    ) -> CorrelationMatrix:
        if self._raise_on_correlation:
            raise self._raise_on_correlation
        return self._correlation_matrix or CorrelationMatrix(
            symbols=["AAPL"],
            entries=[
                CorrelationEntry(
                    symbol_a="AAPL",
                    symbol_b="AAPL",
                    correlation=Decimal("1.000000"),
                    lookback_days=lookback_days,
                ),
            ],
            matrix=[["1.000000"]],
            lookback_days=lookback_days,
            computed_at=_NOW,
        )

    def compute_concentration(self, deployment_id: str) -> ConcentrationReport:
        if self._raise_on_concentration:
            raise self._raise_on_concentration
        return self._concentration or ConcentrationReport(
            per_symbol=[
                SymbolConcentration(
                    symbol="AAPL",
                    market_value=Decimal("50000"),
                    pct_of_portfolio=Decimal("50.00"),
                ),
            ],
            herfindahl_index=Decimal("2500.00"),
            top_5_pct=Decimal("50.00"),
            computed_at=_NOW,
        )

    def get_portfolio_risk_summary(
        self, deployment_id: str, lookback_days: int = 252
    ) -> PortfolioRiskSummary:
        return self._summary or PortfolioRiskSummary(
            var=VaRResult(
                var_95=Decimal("2000.00"),
                var_99=Decimal("3000.00"),
                cvar_95=Decimal("2500.00"),
                cvar_99=Decimal("3500.00"),
                method="historical",
                lookback_days=lookback_days,
                computed_at=_NOW,
            ),
            correlation=CorrelationMatrix(
                symbols=["AAPL"],
                entries=[],
                matrix=[["1.0"]],
                lookback_days=lookback_days,
                computed_at=_NOW,
            ),
            concentration=ConcentrationReport(
                per_symbol=[],
                herfindahl_index=Decimal("0"),
                top_5_pct=Decimal("0"),
                computed_at=_NOW,
            ),
            total_exposure=Decimal("100000"),
            net_exposure=Decimal("100000"),
            gross_exposure=Decimal("100000"),
            long_exposure=Decimal("100000"),
            short_exposure=Decimal("0"),
        )


# ---------------------------------------------------------------------------
# Mock incident manager
# ---------------------------------------------------------------------------


class MockIncidentManager:
    """Records create_incident calls for verification."""

    def __init__(self) -> None:
        self.incidents: list[dict[str, Any]] = []

    def create_incident(
        self,
        *,
        trigger_type: AlertTriggerType,
        title: str,
        details: dict,
        affected_services: list[str],
    ) -> None:
        self.incidents.append(
            {
                "trigger_type": trigger_type,
                "title": title,
                "details": details,
                "affected_services": affected_services,
            }
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_service(
    analytics: MockRiskAnalyticsService | None = None,
    config_repo: MockRiskAlertConfigRepository | None = None,
    incident_manager: MockIncidentManager | None = None,
) -> tuple[
    RiskAlertService,
    MockRiskAnalyticsService,
    MockRiskAlertConfigRepository,
    MockIncidentManager | None,
]:
    a = analytics or MockRiskAnalyticsService()
    r = config_repo or MockRiskAlertConfigRepository()
    service = RiskAlertService(
        risk_analytics=a,
        config_repo=r,
        incident_manager=incident_manager,
    )
    return service, a, r, incident_manager


# ---------------------------------------------------------------------------
# Evaluate alerts — VaR breach
# ---------------------------------------------------------------------------


class TestVaRBreachDetection:
    """Tests for VaR threshold breach detection."""

    def test_var_breach_detected(self) -> None:
        """VaR 95% above threshold triggers alert."""
        im = MockIncidentManager()
        service, analytics, config_repo, _ = _make_service(incident_manager=im)

        # VaR = 6000 on 100000 gross exposure = 6%
        analytics.set_var_result(
            VaRResult(
                var_95=Decimal("6000.00"),
                var_99=Decimal("8000.00"),
                cvar_95=Decimal("7000.00"),
                cvar_99=Decimal("9000.00"),
                method="historical",
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)

        var_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.VAR_BREACH
        ]
        assert len(var_alerts) == 1
        assert var_alerts[0].current_value == Decimal("6.00")
        assert var_alerts[0].threshold_value == Decimal("5.0")
        assert len(im.incidents) >= 1
        assert im.incidents[0]["trigger_type"] == AlertTriggerType.VAR_THRESHOLD_BREACH

    def test_var_below_threshold_no_alert(self) -> None:
        """VaR below threshold does not trigger alert."""
        service, analytics, _, _ = _make_service()

        # VaR = 3000 on 100000 gross = 3%
        analytics.set_var_result(
            VaRResult(
                var_95=Decimal("3000.00"),
                var_99=Decimal("4000.00"),
                cvar_95=Decimal("3500.00"),
                cvar_99=Decimal("4500.00"),
                method="historical",
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)
        var_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.VAR_BREACH
        ]
        assert len(var_alerts) == 0

    def test_var_evaluation_failure_logged_not_raised(self) -> None:
        """VaR computation failure does not prevent other evaluations."""
        service, analytics, _, _ = _make_service()
        analytics.set_raise_on_var(RuntimeError("VaR computation failed"))

        result = service.evaluate_alerts(_DEPLOY_ID)
        # Should still complete with concentration and correlation checks
        assert result.total_rules_checked == 3


# ---------------------------------------------------------------------------
# Evaluate alerts — Concentration breach
# ---------------------------------------------------------------------------


class TestConcentrationBreachDetection:
    """Tests for concentration threshold breach detection."""

    def test_concentration_breach_detected(self) -> None:
        """Single position above threshold triggers alert."""
        im = MockIncidentManager()
        service, analytics, _, _ = _make_service(incident_manager=im)

        analytics.set_concentration(
            ConcentrationReport(
                per_symbol=[
                    SymbolConcentration(
                        symbol="AAPL",
                        market_value=Decimal("40000"),
                        pct_of_portfolio=Decimal("40.00"),
                    ),
                    SymbolConcentration(
                        symbol="MSFT",
                        market_value=Decimal("20000"),
                        pct_of_portfolio=Decimal("20.00"),
                    ),
                ],
                herfindahl_index=Decimal("2000.00"),
                top_5_pct=Decimal("60.00"),
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)

        conc_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.CONCENTRATION_BREACH
        ]
        assert len(conc_alerts) == 1
        assert conc_alerts[0].symbol == "AAPL"
        assert conc_alerts[0].current_value == Decimal("40.00")

    def test_concentration_below_threshold_no_alert(self) -> None:
        """No position above threshold → no alert."""
        service, analytics, _, _ = _make_service()

        analytics.set_concentration(
            ConcentrationReport(
                per_symbol=[
                    SymbolConcentration(
                        symbol="AAPL",
                        market_value=Decimal("25000"),
                        pct_of_portfolio=Decimal("25.00"),
                    ),
                    SymbolConcentration(
                        symbol="MSFT",
                        market_value=Decimal("25000"),
                        pct_of_portfolio=Decimal("25.00"),
                    ),
                ],
                herfindahl_index=Decimal("1250.00"),
                top_5_pct=Decimal("50.00"),
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)
        conc_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.CONCENTRATION_BREACH
        ]
        assert len(conc_alerts) == 0

    def test_multiple_concentration_breaches(self) -> None:
        """Multiple positions above threshold → multiple alerts."""
        service, analytics, _, _ = _make_service()

        # Set threshold low
        config = RiskAlertConfig(
            deployment_id=_DEPLOY_ID,
            concentration_threshold_pct=Decimal("20.0"),
        )
        _, _, config_repo, _ = _make_service()
        service._config_repo.save(config)  # type: ignore[attr-defined]

        analytics.set_concentration(
            ConcentrationReport(
                per_symbol=[
                    SymbolConcentration(
                        symbol="AAPL",
                        market_value=Decimal("35000"),
                        pct_of_portfolio=Decimal("35.00"),
                    ),
                    SymbolConcentration(
                        symbol="MSFT",
                        market_value=Decimal("30000"),
                        pct_of_portfolio=Decimal("30.00"),
                    ),
                ],
                herfindahl_index=Decimal("2125.00"),
                top_5_pct=Decimal("65.00"),
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)
        conc_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.CONCENTRATION_BREACH
        ]
        assert len(conc_alerts) == 2


# ---------------------------------------------------------------------------
# Evaluate alerts — Correlation spike
# ---------------------------------------------------------------------------


class TestCorrelationSpikeDetection:
    """Tests for correlation spike detection."""

    def test_correlation_spike_detected(self) -> None:
        """Pairwise correlation above threshold triggers alert."""
        im = MockIncidentManager()
        service, analytics, _, _ = _make_service(incident_manager=im)

        analytics.set_correlation_matrix(
            CorrelationMatrix(
                symbols=["AAPL", "MSFT"],
                entries=[
                    CorrelationEntry(
                        symbol_a="AAPL",
                        symbol_b="AAPL",
                        correlation=Decimal("1.000000"),
                        lookback_days=252,
                    ),
                    CorrelationEntry(
                        symbol_a="AAPL",
                        symbol_b="MSFT",
                        correlation=Decimal("0.950000"),
                        lookback_days=252,
                    ),
                    CorrelationEntry(
                        symbol_a="MSFT",
                        symbol_b="AAPL",
                        correlation=Decimal("0.950000"),
                        lookback_days=252,
                    ),
                    CorrelationEntry(
                        symbol_a="MSFT",
                        symbol_b="MSFT",
                        correlation=Decimal("1.000000"),
                        lookback_days=252,
                    ),
                ],
                matrix=[["1.000000", "0.950000"], ["0.950000", "1.000000"]],
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)

        corr_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.CORRELATION_SPIKE
        ]
        # Should have exactly 1 alert (not 2 — deduplicated pair)
        assert len(corr_alerts) == 1
        assert corr_alerts[0].current_value == Decimal("0.950000")

    def test_correlation_below_threshold_no_alert(self) -> None:
        """Correlation below threshold → no alert."""
        service, analytics, _, _ = _make_service()

        analytics.set_correlation_matrix(
            CorrelationMatrix(
                symbols=["AAPL", "MSFT"],
                entries=[
                    CorrelationEntry(
                        symbol_a="AAPL",
                        symbol_b="AAPL",
                        correlation=Decimal("1.000000"),
                        lookback_days=252,
                    ),
                    CorrelationEntry(
                        symbol_a="AAPL",
                        symbol_b="MSFT",
                        correlation=Decimal("0.500000"),
                        lookback_days=252,
                    ),
                    CorrelationEntry(
                        symbol_a="MSFT",
                        symbol_b="AAPL",
                        correlation=Decimal("0.500000"),
                        lookback_days=252,
                    ),
                    CorrelationEntry(
                        symbol_a="MSFT",
                        symbol_b="MSFT",
                        correlation=Decimal("1.000000"),
                        lookback_days=252,
                    ),
                ],
                matrix=[["1.000000", "0.500000"], ["0.500000", "1.000000"]],
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)
        corr_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.CORRELATION_SPIKE
        ]
        assert len(corr_alerts) == 0

    def test_self_correlation_excluded(self) -> None:
        """Self-correlation (diagonal 1.0) should never trigger alert."""
        service, analytics, _, _ = _make_service()

        # Set threshold very low so self-correlation would trigger if not excluded
        service._config_repo.save(  # type: ignore[attr-defined]
            RiskAlertConfig(deployment_id=_DEPLOY_ID, correlation_threshold=Decimal("0.50"))
        )

        analytics.set_correlation_matrix(
            CorrelationMatrix(
                symbols=["AAPL"],
                entries=[
                    CorrelationEntry(
                        symbol_a="AAPL",
                        symbol_b="AAPL",
                        correlation=Decimal("1.000000"),
                        lookback_days=252,
                    ),
                ],
                matrix=[["1.000000"]],
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)
        corr_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.CORRELATION_SPIKE
        ]
        assert len(corr_alerts) == 0


# ---------------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------------


class TestConfigManagement:
    """Tests for alert configuration CRUD."""

    def test_get_config_returns_defaults(self) -> None:
        """Default config when none persisted."""
        service, _, _, _ = _make_service()
        config = service.get_config(_DEPLOY_ID)

        assert config.deployment_id == _DEPLOY_ID
        assert config.var_threshold_pct == Decimal("5.0")
        assert config.enabled is True

    def test_update_config_persists(self) -> None:
        """update_config persists to repository."""
        service, _, config_repo, _ = _make_service()

        new_config = RiskAlertConfig(
            deployment_id=_DEPLOY_ID,
            var_threshold_pct=Decimal("3.0"),
            concentration_threshold_pct=Decimal("20.0"),
            enabled=False,
        )
        saved = service.update_config(new_config)

        assert saved.var_threshold_pct == Decimal("3.0")
        assert config_repo.count() == 1

    def test_get_config_after_update(self) -> None:
        """get_config returns persisted config after update."""
        service, _, _, _ = _make_service()

        new_config = RiskAlertConfig(
            deployment_id=_DEPLOY_ID,
            var_threshold_pct=Decimal("7.0"),
        )
        service.update_config(new_config)
        retrieved = service.get_config(_DEPLOY_ID)

        assert retrieved.var_threshold_pct == Decimal("7.0")

    def test_list_configs_empty(self) -> None:
        service, _, _, _ = _make_service()
        assert service.list_configs() == []

    def test_list_configs_returns_all(self) -> None:
        service, _, _, _ = _make_service()
        service.update_config(RiskAlertConfig(deployment_id="01H_A"))
        service.update_config(RiskAlertConfig(deployment_id="01H_B"))
        assert len(service.list_configs()) == 2


# ---------------------------------------------------------------------------
# Disabled config
# ---------------------------------------------------------------------------


class TestDisabledConfig:
    """Tests for disabled alert configurations."""

    def test_disabled_config_skips_evaluation(self) -> None:
        """When config is disabled, no rules are checked."""
        service, _, _, _ = _make_service()

        service.update_config(
            RiskAlertConfig(
                deployment_id=_DEPLOY_ID,
                enabled=False,
            )
        )

        result = service.evaluate_alerts(_DEPLOY_ID)
        assert result.total_rules_checked == 0
        assert result.alerts_triggered == []


# ---------------------------------------------------------------------------
# Incident dispatch
# ---------------------------------------------------------------------------


class TestIncidentDispatch:
    """Tests for IncidentManager integration."""

    def test_no_dispatch_without_incident_manager(self) -> None:
        """When incident_manager is None, no dispatch occurs."""
        service, analytics, _, _ = _make_service(incident_manager=None)

        analytics.set_var_result(
            VaRResult(
                var_95=Decimal("10000.00"),
                var_99=Decimal("15000.00"),
                cvar_95=Decimal("12000.00"),
                cvar_99=Decimal("17000.00"),
                method="historical",
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        # Should not raise even though breach is detected
        result = service.evaluate_alerts(_DEPLOY_ID)
        var_alerts = [
            a for a in result.alerts_triggered if a.alert_type == RiskAlertType.VAR_BREACH
        ]
        assert len(var_alerts) == 1

    def test_dispatch_on_breach(self) -> None:
        """Breach dispatches to IncidentManager."""
        im = MockIncidentManager()
        service, analytics, _, _ = _make_service(incident_manager=im)

        analytics.set_var_result(
            VaRResult(
                var_95=Decimal("8000.00"),
                var_99=Decimal("12000.00"),
                cvar_95=Decimal("10000.00"),
                cvar_99=Decimal("14000.00"),
                method="historical",
                lookback_days=252,
                computed_at=_NOW,
            )
        )

        service.evaluate_alerts(_DEPLOY_ID)

        assert len(im.incidents) >= 1
        assert im.incidents[0]["trigger_type"] == AlertTriggerType.VAR_THRESHOLD_BREACH
        assert _DEPLOY_ID in im.incidents[0]["details"]["deployment_id"]
