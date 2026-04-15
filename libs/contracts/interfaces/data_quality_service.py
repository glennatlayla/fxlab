"""
Data quality service interface (port).

Responsibilities:
- Define the abstract contract for data quality evaluation operations.
- Declare methods for anomaly detection, quality scoring, and readiness checks.

Does NOT:
- Implement anomaly detection algorithms (concrete service responsibility).
- Persist data (delegates to DataQualityRepositoryInterface).
- Know about specific database engines or infrastructure.

Dependencies:
- libs.contracts.data_quality: QualityScore, DataAnomaly, QualityReadinessResult
- libs.contracts.market_data: Candle, CandleInterval
- libs.contracts.execution: ExecutionMode

Error conditions:
- evaluate_quality: may raise ExternalServiceError if repository is unavailable.
- detect_anomalies: no exceptions; returns empty list for clean data.
- check_trading_readiness: returns result with all_ready=False on any failure.

Example:
    service: DataQualityServiceInterface = DataQualityService(repo=repo)
    score = service.evaluate_quality("AAPL", CandleInterval.D1, window_minutes=60)
    readiness = service.check_trading_readiness(["AAPL", "MSFT"], ExecutionMode.LIVE)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.data_quality import (
    DataAnomaly,
    QualityReadinessResult,
    QualityScore,
)
from libs.contracts.execution import ExecutionMode
from libs.contracts.market_data import Candle, CandleInterval


class DataQualityServiceInterface(ABC):
    """
    Port interface for data quality evaluation operations.

    Responsibilities:
    - Evaluate market data quality and produce composite scores.
    - Detect anomalies in candle data.
    - Check trading readiness against quality policies.

    Does NOT:
    - Persist results (delegates to repository).
    - Know about HTTP or infrastructure.

    Example:
        service = DataQualityService(repo=repo, market_data_repo=md_repo)
        score = service.evaluate_quality("AAPL", CandleInterval.D1, 60)
    """

    @abstractmethod
    def evaluate_quality(
        self,
        symbol: str,
        interval: CandleInterval,
        window_minutes: int,
    ) -> QualityScore:
        """
        Evaluate data quality for a symbol over the specified time window.

        Fetches candles from the market data repository, runs anomaly detection,
        computes dimension scores, and produces a composite quality score.

        Args:
            symbol: Ticker symbol to evaluate.
            interval: Candle interval to evaluate.
            window_minutes: How many minutes of data to evaluate.

        Returns:
            QualityScore with all dimensions, composite score, and grade.

        Raises:
            ExternalServiceError: If the market data repository is unavailable.

        Example:
            score = service.evaluate_quality("AAPL", CandleInterval.M1, 60)
            # score.grade == QualityGrade.A
        """

    @abstractmethod
    def detect_anomalies(self, candles: list[Candle]) -> list[DataAnomaly]:
        """
        Detect anomalies in a sequence of candles.

        Runs all anomaly detection checks (OHLCV validation, price spikes,
        volume anomalies, timestamp gaps, duplicates) on the provided data.

        Args:
            candles: List of candles to analyze, sorted by timestamp ascending.

        Returns:
            List of detected anomalies (empty if data is clean).

        Example:
            anomalies = service.detect_anomalies(candles)
            critical = [a for a in anomalies if a.severity == AnomalySeverity.CRITICAL]
        """

    @abstractmethod
    def check_trading_readiness(
        self,
        symbols: list[str],
        execution_mode: ExecutionMode,
    ) -> QualityReadinessResult:
        """
        Check whether market data quality meets trading requirements.

        Evaluates the latest quality score for each symbol against the
        quality policy for the given execution mode.

        Args:
            symbols: List of ticker symbols to check.
            execution_mode: The target execution mode (LIVE, PAPER, SHADOW).

        Returns:
            QualityReadinessResult with per-symbol readiness and aggregate status.

        Example:
            result = service.check_trading_readiness(["AAPL"], ExecutionMode.LIVE)
            if not result.all_ready:
                for sym in result.symbols:
                    if not sym.ready:
                        print(f"{sym.symbol}: {sym.blocking_reasons}")
        """
