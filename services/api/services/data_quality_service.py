"""
Data quality service — anomaly detection and quality scoring engine.

Responsibilities:
- Detect anomalies in OHLCV candle data: OHLCV violations, price spikes,
  volume anomalies, timestamp gaps, duplicate bars.
- Compute per-dimension quality scores (completeness, timeliness,
  consistency, accuracy) and a weighted composite score.
- Evaluate trading readiness against per-execution-mode quality policies.
- Persist detected anomalies and computed scores via the data quality repository.

Does NOT:
- Fetch data from external providers (market data repository responsibility).
- Dispatch alerts or notifications (caller responsibility).
- Know about HTTP, queues, or infrastructure.

Dependencies:
- DataQualityRepositoryInterface (injected): anomaly and score persistence.
- MarketDataRepositoryInterface (injected): candle data retrieval.

Raises:
- ExternalServiceError: If either repository is unavailable.

Example:
    service = DataQualityService(
        data_quality_repo=dq_repo,
        market_data_repo=md_repo,
    )
    score = service.evaluate_quality("AAPL", CandleInterval.M1, window_minutes=60)
    readiness = service.check_trading_readiness(["AAPL"], ExecutionMode.LIVE)
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import structlog

from libs.contracts.data_quality import (
    DEFAULT_QUALITY_POLICIES,
    DEFAULT_QUALITY_WEIGHTS,
    AnomalySeverity,
    AnomalyType,
    DataAnomaly,
    DataQualityDimension,
    QualityPolicy,
    QualityReadinessResult,
    QualityScore,
    SymbolReadiness,
    assign_grade,
)
from libs.contracts.execution import ExecutionMode
from libs.contracts.interfaces.data_quality_repository import (
    DataQualityRepositoryInterface,
)
from libs.contracts.interfaces.data_quality_service import (
    DataQualityServiceInterface,
)
from libs.contracts.interfaces.market_data_repository import (
    MarketDataRepositoryInterface,
)
from libs.contracts.market_data import (
    INTERVAL_SECONDS,
    Candle,
    CandleInterval,
    MarketDataQuery,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

#: Default equity price spike threshold as a fraction (10% move).
_PRICE_SPIKE_THRESHOLD_EQUITY: float = 0.10

#: Rolling window size for adaptive price spike detection (number of bars).
_PRICE_SPIKE_ROLLING_WINDOW: int = 20

#: Standard deviation multiplier for volume anomaly detection.
_VOLUME_ANOMALY_SIGMA: float = 3.0

#: Rolling window size for volume anomaly detection (number of bars).
_VOLUME_ROLLING_WINDOW: int = 50

#: Gap factor: a gap is flagged when actual interval > factor × expected interval.
_GAP_FACTOR: float = 2.0


class DataQualityService(DataQualityServiceInterface):
    """
    Production data quality engine.

    Implements anomaly detection and quality scoring for OHLCV market data.
    All mutable state is scoped to individual method calls — this service
    is stateless and thread-safe.

    Responsibilities:
    - Per-candle OHLCV validation (structural integrity).
    - Inter-bar analysis: price spikes, volume anomalies, timestamp gaps, duplicates.
    - Composite quality scoring across four dimensions.
    - Trading readiness checks against configurable policies.
    - Persistence of anomalies and scores to durable storage.

    Does NOT:
    - Own the scheduling of periodic quality evaluations (caller responsibility).
    - Dispatch alerts (caller wires into IncidentManager).
    - Apply market calendar logic (future enhancement).

    Dependencies:
    - DataQualityRepositoryInterface (injected): persistence.
    - MarketDataRepositoryInterface (injected): candle retrieval.

    Example:
        service = DataQualityService(
            data_quality_repo=dq_repo,
            market_data_repo=md_repo,
        )
        anomalies = service.detect_anomalies(candles)
        score = service.evaluate_quality("AAPL", CandleInterval.M1, 60)
    """

    def __init__(
        self,
        *,
        data_quality_repo: DataQualityRepositoryInterface,
        market_data_repo: MarketDataRepositoryInterface,
        price_spike_threshold: float = _PRICE_SPIKE_THRESHOLD_EQUITY,
        volume_anomaly_sigma: float = _VOLUME_ANOMALY_SIGMA,
        gap_factor: float = _GAP_FACTOR,
    ) -> None:
        """
        Initialize the data quality service.

        Args:
            data_quality_repo: Repository for anomaly and score persistence.
            market_data_repo: Repository for fetching candle data.
            price_spike_threshold: Fraction threshold for price spike detection
                (e.g. 0.10 = 10% move). Default: 0.10.
            volume_anomaly_sigma: Number of standard deviations from rolling mean
                to flag a volume anomaly. Default: 3.0.
            gap_factor: Factor by which actual interval must exceed expected
                interval to flag a timestamp gap. Default: 2.0.
        """
        self._dq_repo = data_quality_repo
        self._md_repo = market_data_repo
        self._price_spike_threshold = price_spike_threshold
        self._volume_anomaly_sigma = volume_anomaly_sigma
        self._gap_factor = gap_factor

    # ------------------------------------------------------------------
    # Public API — DataQualityServiceInterface
    # ------------------------------------------------------------------

    def evaluate_quality(
        self,
        symbol: str,
        interval: CandleInterval,
        window_minutes: int,
    ) -> QualityScore:
        """
        Evaluate data quality for a symbol over the specified time window.

        Fetches candles, runs anomaly detection, computes dimension scores,
        and persists both anomalies and the composite score.

        Args:
            symbol: Ticker symbol to evaluate.
            interval: Candle interval to evaluate.
            window_minutes: How many minutes of data to evaluate.

        Returns:
            QualityScore with all dimensions, composite score, and grade.

        Example:
            score = service.evaluate_quality("AAPL", CandleInterval.M1, 60)
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=window_minutes)
        symbol_upper = symbol.upper()

        logger.info(
            "Evaluating data quality",
            extra={
                "operation": "evaluate_quality",
                "component": "DataQualityService",
                "symbol": symbol_upper,
                "interval": interval.value,
                "window_minutes": window_minutes,
            },
        )

        # Fetch candles for the evaluation window
        candles = self._fetch_candles(symbol_upper, interval, window_start, now)

        # Detect anomalies
        anomalies = self.detect_anomalies(candles)

        # Persist anomalies
        if anomalies:
            self._dq_repo.save_anomalies(anomalies)

        # Compute dimension scores
        completeness = self._compute_completeness(
            candles,
            interval,
            window_start,
            now,
        )
        accuracy = self._compute_accuracy(candles, anomalies)
        consistency = self._compute_consistency(candles, anomalies)
        timeliness = self._compute_timeliness(candles, now)

        # Compute composite score
        composite = self._compute_composite(
            completeness=completeness,
            timeliness=timeliness,
            consistency=consistency,
            accuracy=accuracy,
        )

        # Count anomalies
        anomaly_count = len(anomalies)

        # Build score
        grade = assign_grade(composite)
        score = QualityScore(
            symbol=symbol_upper,
            interval=interval,
            window_start=window_start,
            window_end=now,
            completeness=completeness,
            timeliness=timeliness,
            consistency=consistency,
            accuracy=accuracy,
            composite_score=composite,
            anomaly_count=anomaly_count,
            grade=grade,
            scored_at=now,
        )

        # Persist score
        self._dq_repo.save_quality_score(score)

        logger.info(
            "Data quality evaluation complete",
            extra={
                "operation": "evaluate_quality",
                "component": "DataQualityService",
                "symbol": symbol_upper,
                "grade": grade.value,
                "composite_score": round(composite, 4),
                "anomaly_count": anomaly_count,
            },
        )

        return score

    def detect_anomalies(self, candles: list[Candle]) -> list[DataAnomaly]:
        """
        Detect anomalies in a sequence of candles.

        Runs all anomaly detection checks on the provided data:
        1. OHLCV validation (per-candle)
        2. Zero-volume check (per-candle)
        3. Price spike detection (inter-bar, requires ≥2 candles)
        4. Volume anomaly detection (inter-bar, requires ≥ rolling window)
        5. Timestamp gap detection (inter-bar, requires ≥2 candles)
        6. Duplicate bar detection (requires ≥2 candles)

        Args:
            candles: List of candles to analyze. Should be sorted by timestamp
                ascending for correct inter-bar analysis.

        Returns:
            List of detected anomalies (empty if data is clean).

        Example:
            anomalies = service.detect_anomalies(candles)
        """
        if not candles:
            return []

        anomalies: list[DataAnomaly] = []

        # Sort by timestamp to ensure correct ordering
        sorted_candles = sorted(candles, key=lambda c: c.timestamp)

        # Per-candle checks
        for candle in sorted_candles:
            anomalies.extend(self._check_ohlcv(candle))
            anomalies.extend(self._check_zero_volume(candle))

        # Inter-bar checks (require ≥ 2 candles)
        if len(sorted_candles) >= 2:
            anomalies.extend(self._check_price_spikes(sorted_candles))
            anomalies.extend(self._check_volume_anomalies(sorted_candles))
            anomalies.extend(self._check_timestamp_gaps(sorted_candles))
            anomalies.extend(self._check_duplicates(sorted_candles))

        return anomalies

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
            QualityReadinessResult with per-symbol readiness.

        Example:
            result = service.check_trading_readiness(["AAPL"], ExecutionMode.LIVE)
        """
        now = datetime.now(timezone.utc)
        policy = DEFAULT_QUALITY_POLICIES.get(execution_mode)

        # Fallback policy for unknown modes (should not happen with typed enum)
        if policy is None:
            policy = QualityPolicy(
                execution_mode=execution_mode,
                min_composite_score=0.90,
                min_completeness=0.95,
                max_anomaly_severity=AnomalySeverity.WARNING,
                lookback_window_minutes=60,
            )

        symbol_results: list[SymbolReadiness] = []
        all_ready = True

        for symbol in symbols:
            symbol_upper = symbol.upper()
            # Use CandleInterval.M1 as the default check interval
            latest_score = self._dq_repo.get_latest_score(
                symbol_upper,
                CandleInterval.M1,
            )

            blocking: list[str] = []
            ready = True

            if latest_score is None:
                ready = False
                blocking.append("No quality score available")
            else:
                # Check composite score threshold
                if latest_score.composite_score < policy.min_composite_score:
                    ready = False
                    blocking.append(
                        f"Composite score {latest_score.composite_score:.2f} "
                        f"< min {policy.min_composite_score:.2f}"
                    )

                # Check completeness threshold
                if latest_score.completeness < policy.min_completeness:
                    ready = False
                    blocking.append(
                        f"Completeness {latest_score.completeness:.2f} "
                        f"< min {policy.min_completeness:.2f}"
                    )

                # Check for critical anomalies in lookback window
                lookback_since = now - timedelta(
                    minutes=policy.lookback_window_minutes,
                )
                if policy.max_anomaly_severity == AnomalySeverity.WARNING:
                    # For LIVE: reject if any CRITICAL anomalies exist
                    critical_count = self._dq_repo.count_anomalies(
                        symbol_upper,
                        CandleInterval.M1,
                        since=lookback_since,
                        severity=AnomalySeverity.CRITICAL,
                    )
                    if critical_count > 0:
                        ready = False
                        blocking.append(f"{critical_count} CRITICAL anomalies in lookback window")

            if not ready:
                all_ready = False

            symbol_results.append(
                SymbolReadiness(
                    symbol=symbol_upper,
                    ready=ready,
                    quality_score=latest_score,
                    blocking_reasons=blocking,
                )
            )

        return QualityReadinessResult(
            execution_mode=execution_mode,
            all_ready=all_ready,
            symbols=symbol_results,
            policy=policy,
            evaluated_at=now,
        )

    # ------------------------------------------------------------------
    # Repository delegation — read-through methods for controller layer
    # ------------------------------------------------------------------

    def get_latest_score(
        self,
        symbol: str,
        interval: CandleInterval,
    ) -> QualityScore | None:
        """
        Get the most recent quality score for a symbol and interval.

        Delegates to the data quality repository. Controllers call this
        method instead of accessing the repository directly.

        Args:
            symbol: Ticker symbol (case-insensitive).
            interval: Candle interval.

        Returns:
            The most recent QualityScore, or None if no scores exist.

        Example:
            score = service.get_latest_score("AAPL", CandleInterval.D1)
        """
        return self._dq_repo.get_latest_score(symbol.upper(), interval)

    def get_score_history(
        self,
        symbol: str,
        interval: CandleInterval,
        since: datetime,
        limit: int = 100,
    ) -> list[QualityScore]:
        """
        Get historical quality scores for a symbol and interval.

        Delegates to the data quality repository.

        Args:
            symbol: Ticker symbol (case-insensitive).
            interval: Candle interval.
            since: Only return scores with window_start after this time.
            limit: Maximum number of results (default 100).

        Returns:
            List of QualityScore objects, newest first.

        Example:
            history = service.get_score_history("AAPL", CandleInterval.D1, since=cutoff)
        """
        return self._dq_repo.get_score_history(symbol.upper(), interval, since, limit)

    def find_anomalies(
        self,
        symbol: str,
        interval: CandleInterval,
        since: datetime,
        severity: AnomalySeverity | None = None,
        limit: int = 100,
    ) -> list[DataAnomaly]:
        """
        Query anomalies by symbol, interval, and time range.

        Delegates to the data quality repository.

        Args:
            symbol: Ticker symbol (case-insensitive).
            interval: Candle interval.
            since: Only return anomalies detected after this time.
            severity: Optional severity filter.
            limit: Maximum number of results (default 100).

        Returns:
            List of DataAnomaly objects, newest first.

        Example:
            anomalies = service.find_anomalies("AAPL", CandleInterval.M1, since=cutoff)
        """
        return self._dq_repo.find_anomalies(
            symbol.upper(),
            interval,
            since,
            severity=severity,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Private: candle fetching
    # ------------------------------------------------------------------

    def _fetch_candles(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Fetch candles from the market data repository for the given window.

        Fetches up to 10,000 candles in a single query. If more exist, this
        is adequate for quality evaluation (we don't need every single candle
        to compute quality metrics, and 10,000 1-minute bars ≈ 7 trading days).

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Window start.
            end: Window end.

        Returns:
            List of candles, possibly empty.
        """
        query = MarketDataQuery(
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            limit=10_000,
        )
        page = self._md_repo.query_candles(query)
        return page.candles

    # ------------------------------------------------------------------
    # Private: per-candle anomaly checks
    # ------------------------------------------------------------------

    def _check_ohlcv(self, candle: Candle) -> list[DataAnomaly]:
        """
        Validate OHLCV relationships for a single candle.

        Rules:
        - high >= max(open, close)
        - low <= min(open, close)
        - high >= low

        Any violation is CRITICAL because it indicates corrupt data that
        would produce incorrect indicator calculations.

        Args:
            candle: The candle to validate.

        Returns:
            List of OHLCV_VIOLATION anomalies (empty if valid).
        """
        anomalies: list[DataAnomaly] = []

        violations: list[str] = []

        if candle.high < candle.low:
            violations.append(f"high ({candle.high}) < low ({candle.low})")

        if candle.high < candle.open:
            violations.append(f"high ({candle.high}) < open ({candle.open})")

        if candle.high < candle.close:
            violations.append(f"high ({candle.high}) < close ({candle.close})")

        if candle.low > candle.open:
            violations.append(f"low ({candle.low}) > open ({candle.open})")

        if candle.low > candle.close:
            violations.append(f"low ({candle.low}) > close ({candle.close})")

        if violations:
            anomalies.append(
                DataAnomaly(
                    anomaly_id=self._gen_id(),
                    symbol=candle.symbol,
                    interval=candle.interval,
                    anomaly_type=AnomalyType.OHLCV_VIOLATION,
                    severity=AnomalySeverity.CRITICAL,
                    detected_at=datetime.now(timezone.utc),
                    bar_timestamp=candle.timestamp,
                    details={"violations": violations},
                )
            )

        return anomalies

    def _check_zero_volume(self, candle: Candle) -> list[DataAnomaly]:
        """
        Check for zero volume on a candle with price movement.

        Zero volume with non-zero price difference (open != close) is suspicious
        and flagged as WARNING. Zero volume with open == close may be legitimate
        (no trades in the interval) and is flagged as INFO.

        Args:
            candle: The candle to check.

        Returns:
            List of VOLUME_ANOMALY anomalies (empty if volume > 0).
        """
        if candle.volume > 0:
            return []

        has_price_movement = candle.open != candle.close
        severity = AnomalySeverity.WARNING if has_price_movement else AnomalySeverity.INFO

        return [
            DataAnomaly(
                anomaly_id=self._gen_id(),
                symbol=candle.symbol,
                interval=candle.interval,
                anomaly_type=AnomalyType.VOLUME_ANOMALY,
                severity=severity,
                detected_at=datetime.now(timezone.utc),
                bar_timestamp=candle.timestamp,
                details={
                    "volume": 0,
                    "has_price_movement": has_price_movement,
                },
            )
        ]

    # ------------------------------------------------------------------
    # Private: inter-bar anomaly checks
    # ------------------------------------------------------------------

    def _check_price_spikes(self, candles: list[Candle]) -> list[DataAnomaly]:
        """
        Detect price spikes by comparing bar-to-bar close price changes.

        A spike is flagged when the absolute percentage change between
        consecutive closes exceeds the configured threshold.

        For adaptive detection with sufficient history, the threshold is
        the maximum of: (a) the configured static threshold, or (b) 3×
        the rolling standard deviation of close-to-close returns.

        Args:
            candles: Sorted list of candles (≥ 2).

        Returns:
            List of PRICE_SPIKE anomalies.
        """
        anomalies: list[DataAnomaly] = []
        closes = [float(c.close) for c in candles]

        for i in range(1, len(candles)):
            prev_close = closes[i - 1]
            curr_close = closes[i]

            if prev_close == 0:
                continue  # Cannot compute % change from zero base

            pct_change = abs(curr_close - prev_close) / prev_close

            # Adaptive threshold: use rolling stddev if enough history
            effective_threshold = self._price_spike_threshold
            if i >= _PRICE_SPIKE_ROLLING_WINDOW:
                window_returns = []
                for j in range(i - _PRICE_SPIKE_ROLLING_WINDOW, i):
                    if closes[j] != 0:
                        ret = abs(closes[j + 1] - closes[j]) / closes[j]
                        window_returns.append(ret)
                if len(window_returns) >= 2:
                    mean_ret = sum(window_returns) / len(window_returns)
                    variance = sum((r - mean_ret) ** 2 for r in window_returns) / (
                        len(window_returns) - 1
                    )
                    stddev = math.sqrt(variance)
                    adaptive_threshold = mean_ret + 3 * stddev
                    effective_threshold = max(
                        self._price_spike_threshold,
                        adaptive_threshold,
                    )

            if pct_change > effective_threshold:
                severity = (
                    AnomalySeverity.CRITICAL
                    if pct_change > effective_threshold * 2
                    else AnomalySeverity.WARNING
                )
                anomalies.append(
                    DataAnomaly(
                        anomaly_id=self._gen_id(),
                        symbol=candles[i].symbol,
                        interval=candles[i].interval,
                        anomaly_type=AnomalyType.PRICE_SPIKE,
                        severity=severity,
                        detected_at=datetime.now(timezone.utc),
                        bar_timestamp=candles[i].timestamp,
                        details={
                            "pct_change": round(pct_change, 6),
                            "threshold": round(effective_threshold, 6),
                            "prev_close": str(candles[i - 1].close),
                            "curr_close": str(candles[i].close),
                        },
                    )
                )

        return anomalies

    def _check_volume_anomalies(self, candles: list[Candle]) -> list[DataAnomaly]:
        """
        Detect volume anomalies by comparing each bar's volume against a
        rolling mean ± N standard deviations.

        Only flags bars where volume > 0 and the volume deviates more than
        `_volume_anomaly_sigma` standard deviations from the rolling mean
        of the preceding `_VOLUME_ROLLING_WINDOW` bars.

        Args:
            candles: Sorted list of candles (≥ 2).

        Returns:
            List of VOLUME_ANOMALY anomalies for extreme volume bars.
        """
        anomalies: list[DataAnomaly] = []
        volumes = [c.volume for c in candles]

        # Need sufficient history for rolling statistics
        min_window = min(_VOLUME_ROLLING_WINDOW, len(candles))
        if min_window < 5:
            return anomalies

        for i in range(min_window, len(candles)):
            current_vol = volumes[i]
            if current_vol == 0:
                continue  # Zero volume handled by _check_zero_volume

            # Compute rolling stats from preceding bars
            window_start = max(0, i - _VOLUME_ROLLING_WINDOW)
            window = volumes[window_start:i]

            if len(window) < 2:
                continue

            mean_vol = sum(window) / len(window)
            if mean_vol == 0:
                continue  # All zero volumes in window, cannot detect deviation

            variance = sum((v - mean_vol) ** 2 for v in window) / (len(window) - 1)
            stddev = math.sqrt(variance)

            if stddev == 0:
                # All volumes identical in window; any deviation is anomalous
                if current_vol != mean_vol:
                    anomalies.append(
                        DataAnomaly(
                            anomaly_id=self._gen_id(),
                            symbol=candles[i].symbol,
                            interval=candles[i].interval,
                            anomaly_type=AnomalyType.VOLUME_ANOMALY,
                            severity=AnomalySeverity.WARNING,
                            detected_at=datetime.now(timezone.utc),
                            bar_timestamp=candles[i].timestamp,
                            details={
                                "volume": current_vol,
                                "rolling_mean": round(mean_vol, 2),
                                "rolling_stddev": 0.0,
                                "sigma_deviation": float("inf"),
                            },
                        )
                    )
                continue

            sigma_deviation = abs(current_vol - mean_vol) / stddev
            if sigma_deviation > self._volume_anomaly_sigma:
                anomalies.append(
                    DataAnomaly(
                        anomaly_id=self._gen_id(),
                        symbol=candles[i].symbol,
                        interval=candles[i].interval,
                        anomaly_type=AnomalyType.VOLUME_ANOMALY,
                        severity=AnomalySeverity.WARNING,
                        detected_at=datetime.now(timezone.utc),
                        bar_timestamp=candles[i].timestamp,
                        details={
                            "volume": current_vol,
                            "rolling_mean": round(mean_vol, 2),
                            "rolling_stddev": round(stddev, 2),
                            "sigma_deviation": round(sigma_deviation, 2),
                        },
                    )
                )

        return anomalies

    def _check_timestamp_gaps(self, candles: list[Candle]) -> list[DataAnomaly]:
        """
        Detect timestamp gaps between consecutive candles.

        A gap is flagged when the time between consecutive candles exceeds
        `gap_factor` × the expected interval duration (from INTERVAL_SECONDS).

        Args:
            candles: Sorted list of candles (≥ 2) with the same interval.

        Returns:
            List of TIMESTAMP_GAP anomalies.
        """
        anomalies: list[DataAnomaly] = []

        if len(candles) < 2:
            return anomalies

        interval = candles[0].interval
        expected_seconds = INTERVAL_SECONDS.get(interval)
        if expected_seconds is None:
            return anomalies

        max_gap_seconds = expected_seconds * self._gap_factor

        for i in range(1, len(candles)):
            actual_seconds = (candles[i].timestamp - candles[i - 1].timestamp).total_seconds()

            if actual_seconds > max_gap_seconds:
                anomalies.append(
                    DataAnomaly(
                        anomaly_id=self._gen_id(),
                        symbol=candles[i].symbol,
                        interval=candles[i].interval,
                        anomaly_type=AnomalyType.TIMESTAMP_GAP,
                        severity=AnomalySeverity.WARNING,
                        detected_at=datetime.now(timezone.utc),
                        bar_timestamp=candles[i].timestamp,
                        details={
                            "gap_seconds": actual_seconds,
                            "expected_seconds": expected_seconds,
                            "gap_factor": round(actual_seconds / expected_seconds, 2),
                            "gap_start": candles[i - 1].timestamp.isoformat(),
                            "gap_end": candles[i].timestamp.isoformat(),
                        },
                    )
                )

        return anomalies

    def _check_duplicates(self, candles: list[Candle]) -> list[DataAnomaly]:
        """
        Detect duplicate bars — multiple candles with the same timestamp
        for the same (symbol, interval).

        Args:
            candles: Sorted list of candles (≥ 2).

        Returns:
            List of DUPLICATE_BAR anomalies.
        """
        anomalies: list[DataAnomaly] = []
        seen: set[tuple[str, str, str]] = set()

        for candle in candles:
            key = (candle.symbol, candle.interval.value, candle.timestamp.isoformat())
            if key in seen:
                anomalies.append(
                    DataAnomaly(
                        anomaly_id=self._gen_id(),
                        symbol=candle.symbol,
                        interval=candle.interval,
                        anomaly_type=AnomalyType.DUPLICATE_BAR,
                        severity=AnomalySeverity.WARNING,
                        detected_at=datetime.now(timezone.utc),
                        bar_timestamp=candle.timestamp,
                        details={
                            "duplicate_key": f"{candle.symbol}:{candle.interval.value}:{candle.timestamp.isoformat()}"
                        },
                    )
                )
            else:
                seen.add(key)

        return anomalies

    # ------------------------------------------------------------------
    # Private: dimension scoring
    # ------------------------------------------------------------------

    def _compute_completeness(
        self,
        candles: list[Candle],
        interval: CandleInterval,
        window_start: datetime,
        window_end: datetime,
    ) -> float:
        """
        Compute completeness score: actual bars / expected bars.

        The expected bar count is derived from the window duration divided
        by the interval duration. This is a simplified calculation that
        does not account for market hours — a future enhancement can
        subtract weekends, holidays, and pre/post-market gaps.

        Args:
            candles: Actual candles in the window.
            interval: Candle interval.
            window_start: Window start time.
            window_end: Window end time.

        Returns:
            Completeness score in [0.0, 1.0].
        """
        expected_seconds = INTERVAL_SECONDS.get(interval)
        if expected_seconds is None or expected_seconds == 0:
            return 1.0 if candles else 0.0

        window_seconds = (window_end - window_start).total_seconds()
        expected_count = max(1, int(window_seconds / expected_seconds))

        actual_count = len(candles)
        return min(1.0, actual_count / expected_count)

    def _compute_accuracy(
        self,
        candles: list[Candle],
        anomalies: list[DataAnomaly],
    ) -> float:
        """
        Compute accuracy score: fraction of candles without OHLCV violations.

        Args:
            candles: All candles evaluated.
            anomalies: All detected anomalies.

        Returns:
            Accuracy score in [0.0, 1.0]. Returns 1.0 if no candles.
        """
        if not candles:
            return 1.0

        ohlcv_violations = sum(
            1 for a in anomalies if a.anomaly_type == AnomalyType.OHLCV_VIOLATION
        )
        return max(0.0, 1.0 - (ohlcv_violations / len(candles)))

    def _compute_consistency(
        self,
        candles: list[Candle],
        anomalies: list[DataAnomaly],
    ) -> float:
        """
        Compute consistency score: fraction of candles without inter-bar anomalies.

        Considers: PRICE_SPIKE, TIMESTAMP_GAP, DUPLICATE_BAR anomalies.
        Higher count of inter-bar anomalies lowers consistency.

        Args:
            candles: All candles evaluated.
            anomalies: All detected anomalies.

        Returns:
            Consistency score in [0.0, 1.0]. Returns 1.0 if ≤1 candle.
        """
        if len(candles) <= 1:
            return 1.0

        inter_bar_types = {
            AnomalyType.PRICE_SPIKE,
            AnomalyType.TIMESTAMP_GAP,
            AnomalyType.DUPLICATE_BAR,
        }
        inter_bar_count = sum(1 for a in anomalies if a.anomaly_type in inter_bar_types)
        # Normalize against the number of inter-bar transitions
        transition_count = len(candles) - 1
        return max(0.0, 1.0 - (inter_bar_count / transition_count))

    def _compute_timeliness(
        self,
        candles: list[Candle],
        evaluation_time: datetime,
    ) -> float:
        """
        Compute timeliness score based on data freshness.

        Measures how recent the latest candle is relative to the evaluation time.
        A candle within 2× the expected interval is considered timely (score 1.0).
        Score degrades linearly as data ages, reaching 0.0 at 10× the expected
        interval.

        Args:
            candles: All candles evaluated.
            evaluation_time: When the evaluation is being performed.

        Returns:
            Timeliness score in [0.0, 1.0]. Returns 0.5 if no candles.
        """
        if not candles:
            return 0.5  # Neutral when no data (penalized via completeness instead)

        latest = max(candles, key=lambda c: c.timestamp)
        interval = latest.interval
        expected_seconds = INTERVAL_SECONDS.get(interval, 60)

        age_seconds = (evaluation_time - latest.timestamp).total_seconds()

        # Fresh: within 2× expected interval → 1.0
        fresh_threshold = expected_seconds * 2
        if age_seconds <= fresh_threshold:
            return 1.0

        # Stale: degrades linearly from 1.0 to 0.0 over 2× to 10× expected interval
        stale_threshold = expected_seconds * 10
        if age_seconds >= stale_threshold:
            return 0.0

        return 1.0 - (age_seconds - fresh_threshold) / (stale_threshold - fresh_threshold)

    def _compute_composite(
        self,
        *,
        completeness: float,
        timeliness: float,
        consistency: float,
        accuracy: float,
    ) -> float:
        """
        Compute weighted composite quality score.

        Uses DEFAULT_QUALITY_WEIGHTS to produce a single score from the
        four quality dimensions.

        Args:
            completeness: Completeness score [0.0, 1.0].
            timeliness: Timeliness score [0.0, 1.0].
            consistency: Consistency score [0.0, 1.0].
            accuracy: Accuracy score [0.0, 1.0].

        Returns:
            Composite score in [0.0, 1.0].
        """
        weights = DEFAULT_QUALITY_WEIGHTS
        composite = (
            completeness * weights[DataQualityDimension.COMPLETENESS]
            + timeliness * weights[DataQualityDimension.TIMELINESS]
            + consistency * weights[DataQualityDimension.CONSISTENCY]
            + accuracy * weights[DataQualityDimension.ACCURACY]
        )
        return max(0.0, min(1.0, composite))

    # ------------------------------------------------------------------
    # Private: utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _gen_id() -> str:
        """
        Generate a unique anomaly ID.

        Uses UUID4 for simplicity. Production deployments may substitute
        ULID for time-ordered identifiers.

        Returns:
            Unique string identifier.
        """
        return str(uuid.uuid4())
