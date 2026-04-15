"""
ComplianceReportServiceInterface — port for compliance report generation.

Purpose:
    Define the contract for regulatory compliance reporting operations
    so that route handlers and data consumers depend on an abstraction,
    not a concrete implementation.

Responsibilities:
    - get_execution_report() → generate execution compliance reports.
    - get_best_execution() → analyze best execution quality metrics.
    - get_venue_routing() → summarize venue routing statistics.
    - get_monthly_summary() → generate monthly aggregate summaries.
    - export_csv() → export execution reports in CSV format.

Does NOT:
    - Parse HTTP requests (controller responsibility).
    - Access databases or repositories directly (injected by caller).
    - Implement analysis algorithms (delegated to underlying services).

Dependencies:
    - ExecutionAnalysisServiceInterface (injected)
    - OrderRepositoryInterface (injected)
    - OrderFillRepositoryInterface (injected)

Error conditions:
    - ValidationError: Invalid input parameters (date ranges, month format).
    - NotFoundError: Referenced entity does not exist.
    - ExternalServiceError: Database or repository failure.

Example:
    service = ComplianceReportService(
        execution_analysis_service=analysis_svc,
        order_repo=order_repo,
        order_fill_repo=fill_repo,
    )
    report = service.get_execution_report(
        date_from=datetime(2026, 4, 1),
        date_to=datetime(2026, 4, 30),
    )
    csv_data = service.export_csv(report=report)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.compliance_report import (
    BestExecutionReport,
    ExecutionComplianceReport,
    MonthlySummary,
    VenueRoutingReport,
)


class ComplianceReportServiceInterface(ABC):
    """
    Abstract port for compliance report generation service.

    Implementations:
    - ComplianceReportService — production implementation (M11)
    """

    @abstractmethod
    def get_execution_report(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> ExecutionComplianceReport:
        """
        Generate execution compliance report for all orders in a date range.

        Produces a detailed execution report suitable for regulatory review
        (SEC Rule 606, FINRA, MiFID II, etc.). Includes per-order records
        with timestamps, fills, commissions, and execution details.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.
                          If provided, only orders from that deployment are included.

        Returns:
            ExecutionComplianceReport containing summary statistics and
            complete list of order records (ComplianceOrderRecord items).

        Raises:
            ValidationError: If date_from > date_to or parameters are invalid.
            NotFoundError: If deployment_id is specified but not found.
            ExternalServiceError: If underlying repository access fails.

        Example:
            report = service.get_execution_report(
                date_from=datetime(2026, 4, 1),
                date_to=datetime(2026, 4, 30),
                deployment_id="01HDEPLOY123",
            )
            print(f"Total orders: {report.total_orders}")
            print(f"Fill rate: {report.total_filled / report.total_orders * 100}%")
        """
        ...

    @abstractmethod
    def get_best_execution(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> BestExecutionReport:
        """
        Generate best execution analysis report for filled orders.

        Compares actual fill prices against National Best Bid/Offer (NBBO)
        and limit prices to quantify execution quality and price improvement.
        Supports MiFID II and SEC Rule 606(c) best execution reporting.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            BestExecutionReport containing aggregate metrics (average price
            improvement, slippage, latency) and per-order BestExecutionRecord
            entries with detailed price analysis.

        Raises:
            ValidationError: If date_from > date_to or parameters are invalid.
            NotFoundError: If deployment_id is specified but not found.
            ExternalServiceError: If underlying repository access fails.

        Example:
            report = service.get_best_execution(
                date_from=datetime(2026, 4, 1),
                date_to=datetime(2026, 4, 30),
            )
            print(f"Avg price improvement: {report.avg_price_improvement_bps} bps")
            print(f"Orders with improvement: {report.pct_with_price_improvement}%")
        """
        ...

    @abstractmethod
    def get_venue_routing(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> VenueRoutingReport:
        """
        Generate venue routing report with per-venue execution statistics.

        Summarizes order routing and fill performance by execution venue
        (exchange, market center, etc.). Supports venue selection transparency
        and regulatory venue routing disclosure requirements.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            VenueRoutingReport containing per-venue statistics including
            order counts, fill rates, volumes, and latency metrics.

        Raises:
            ValidationError: If date_from > date_to or parameters are invalid.
            NotFoundError: If deployment_id is specified but not found.
            ExternalServiceError: If underlying repository access fails.

        Example:
            report = service.get_venue_routing(
                date_from=datetime(2026, 4, 1),
                date_to=datetime(2026, 4, 30),
            )
            for venue in report.venues:
                print(f"{venue.venue}: {venue.fill_rate}% fill rate")
        """
        ...

    @abstractmethod
    def get_monthly_summary(
        self,
        *,
        month: str,
        deployment_id: str | None = None,
    ) -> MonthlySummary:
        """
        Generate monthly aggregate compliance summary.

        High-level executive summary of trading activity for a single
        calendar month. Used for trend analysis, management reporting,
        and regulatory month-end disclosures.

        Args:
            month: Reporting month in "YYYY-MM" format (e.g., "2026-04").
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            MonthlySummary with key metrics: order counts, fill rate,
            error rate, volume, commissions, symbol/venue diversity.

        Raises:
            ValidationError: If month format is invalid (must be "YYYY-MM").
            NotFoundError: If deployment_id is specified but not found.
            ExternalServiceError: If underlying repository access fails.

        Example:
            summary = service.get_monthly_summary(month="2026-04")
            print(f"Fill rate: {summary.fill_rate}%")
            print(f"Error rate: {summary.error_rate}%")
            print(f"Total volume: {summary.total_volume}")
        """
        ...

    @abstractmethod
    def export_csv(
        self,
        *,
        report: ExecutionComplianceReport,
    ) -> str:
        """
        Export execution compliance report as CSV string.

        Converts an ExecutionComplianceReport into comma-separated values
        format suitable for download, archival, external analysis, or
        regulatory submission. Output includes header row and one row
        per order with all compliance-relevant fields.

        Args:
            report: ExecutionComplianceReport to export.

        Returns:
            CSV string with header row and one row per order. Each row contains:
            order_id, client_order_id, broker_order_id, symbol, side, order_type,
            quantity, filled_quantity, average_fill_price, limit_price, status,
            execution_mode, venue, submitted_at, filled_at, cancelled_at,
            commission, correlation_id.

        Raises:
            ValueError: If report is malformed or contains invalid data.

        Example:
            report = service.get_execution_report(
                date_from=datetime(2026, 4, 1),
                date_to=datetime(2026, 4, 30),
            )
            csv_data = service.export_csv(report=report)
            with open("compliance_2026_04.csv", "w") as f:
                f.write(csv_data)
        """
        ...
