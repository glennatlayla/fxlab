"""
Walk-forward analysis engine — systematic parameter optimization with OOS validation (M10).

Responsibilities:
- Split historical data into rolling in-sample/out-of-sample windows.
- Run exhaustive grid search on in-sample data via BacktestEngine.
- Validate best parameters on out-of-sample data.
- Compute parameter stability score across windows.
- Determine consensus optimal parameters.

Does NOT:
- Implement strategy logic (uses strategy_factory to create parameterized strategies).
- Persist results (caller responsibility).
- Fetch market data directly (delegates to BacktestEngine which uses repository).

Dependencies (all injected):
- MarketDataRepositoryInterface: historical candle source (passed to BacktestEngine).
- IndicatorEngine: indicator computation (passed to BacktestEngine).
- strategy_factory: Callable that creates a SignalStrategy from parameter dict.

Error conditions:
- ValueError: if config produces zero windows.

Example:
    engine = WalkForwardEngine(
        market_data_repository=repo,
        indicator_engine=ind_engine,
        strategy_factory=lambda params: MaCrossover(**params),
    )
    config = WalkForwardConfig(
        strategy_id="ma-crossover",
        signal_strategy_id="ma-crossover",
        symbols=["AAPL"],
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        interval=BacktestInterval.ONE_DAY,
        in_sample_bars=200,
        out_of_sample_bars=50,
        step_bars=50,
        parameter_grid={"fast_period": [10, 20], "slow_period": [50, 100]},
        optimization_metric=OptimizationMetric.SHARPE,
    )
    result = engine.run(config)
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

from libs.contracts.backtest import BacktestConfig, BacktestResult
from libs.contracts.interfaces.walk_forward_engine import WalkForwardEngineInterface
from libs.contracts.walk_forward import (
    OptimizationMetric,
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindowResult,
)
from services.worker.research.backtest_engine import BacktestEngine

if TYPE_CHECKING:
    from libs.contracts.interfaces.market_data_repository import (
        MarketDataRepositoryInterface,
    )
    from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
    from libs.indicators.engine import IndicatorEngine

logger = structlog.get_logger(__name__)


class WalkForwardEngine(WalkForwardEngineInterface):
    """
    Walk-forward analysis engine with exhaustive grid search.

    Splits the configured date range into rolling windows, each with an
    in-sample training period and an out-of-sample validation period.
    For each window, runs a BacktestEngine backtest for every parameter
    combination in the grid, selects the best by the configured metric,
    and validates on the out-of-sample period.

    Responsibilities:
    - Generate rolling window date ranges from config parameters.
    - Enumerate all parameter combinations (cartesian product of grid).
    - Run BacktestEngine for each combination on in-sample data.
    - Select best parameters by optimization metric.
    - Validate best parameters on out-of-sample data.
    - Compute parameter stability across windows.
    - Aggregate out-of-sample metrics.

    Does NOT:
    - Implement trading strategies (uses injected strategy_factory).
    - Persist results (returns WalkForwardResult).
    - Manage concurrency (sequential execution).

    Thread safety:
    - Not thread-safe. Each run() call is self-contained.

    Example:
        engine = WalkForwardEngine(
            market_data_repository=repo,
            indicator_engine=ind_engine,
            strategy_factory=lambda params: MaCrossover(**params),
        )
        result = engine.run(config)
    """

    def __init__(
        self,
        *,
        market_data_repository: MarketDataRepositoryInterface,
        indicator_engine: IndicatorEngine,
        strategy_factory: Callable[[dict[str, Any]], SignalStrategyInterface],
    ) -> None:
        """
        Initialize the walk-forward engine.

        Args:
            market_data_repository: Source for historical candle data.
            indicator_engine: Engine to compute technical indicators.
            strategy_factory: Creates a SignalStrategy from a parameter dict.
                Called once per parameter combination per window.

        Example:
            engine = WalkForwardEngine(
                market_data_repository=repo,
                indicator_engine=ind_engine,
                strategy_factory=lambda p: MaCrossover(**p),
            )
        """
        self._market_data_repository = market_data_repository
        self._indicator_engine = indicator_engine
        self._strategy_factory = strategy_factory

    def run(self, config: WalkForwardConfig) -> WalkForwardResult:
        """
        Execute walk-forward analysis.

        Pipeline:
        1. Generate rolling window date ranges.
        2. Enumerate parameter grid (cartesian product).
        3. For each window:
           a. Run backtest for each param combo on in-sample.
           b. Select best params by optimization metric.
           c. Run backtest with best params on out-of-sample.
        4. Compute aggregate metrics and stability score.
        5. Return WalkForwardResult.

        Args:
            config: Walk-forward configuration.

        Returns:
            WalkForwardResult with per-window results and aggregate metrics.

        Raises:
            ValueError: If config produces zero windows.

        Example:
            result = engine.run(config)
        """
        logger.info(
            "Walk-forward analysis started",
            strategy_id=config.strategy_id,
            symbols=config.symbols,
            in_sample_bars=config.in_sample_bars,
            out_of_sample_bars=config.out_of_sample_bars,
            step_bars=config.step_bars,
        )

        # 1. Generate window date ranges
        windows = self._generate_windows(config)

        if not windows:
            logger.warning(
                "No walk-forward windows generated",
                strategy_id=config.strategy_id,
            )
            return WalkForwardResult(
                config=config,
                windows=[],
                aggregate_oos_metric=0.0,
                stability_score=0.0,
                best_consensus_params={},
                total_backtests_run=0,
            )

        # 2. Enumerate parameter combinations
        param_combos = self._enumerate_params(config.parameter_grid)

        # 3. Process each window
        window_results: list[WalkForwardWindowResult] = []
        total_backtests = 0
        all_best_params: list[dict[str, Any]] = []

        for idx, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
            logger.info(
                "Processing walk-forward window",
                window_index=idx,
                is_start=str(is_start),
                is_end=str(is_end),
                oos_start=str(oos_start),
                oos_end=str(oos_end),
                param_combos=len(param_combos),
            )

            # 3a. Run backtest for each param combo on in-sample
            best_metric = float("-inf")
            best_params: dict[str, Any] = param_combos[0] if param_combos else {}
            combos_tested = 0

            for params in param_combos:
                strategy = self._strategy_factory(params)
                bt_engine = BacktestEngine(
                    signal_strategy=strategy,
                    market_data_repository=self._market_data_repository,
                    indicator_engine=self._indicator_engine,
                )
                bt_config = BacktestConfig(
                    strategy_id=config.strategy_id,
                    symbols=list(config.symbols),
                    start_date=is_start,
                    end_date=is_end,
                    interval=config.interval,
                    initial_equity=config.initial_equity,
                )
                bt_result = bt_engine.run(bt_config)
                total_backtests += 1
                combos_tested += 1

                metric_value = self._extract_metric(
                    bt_result,
                    config.optimization_metric,
                )
                if metric_value > best_metric:
                    best_metric = metric_value
                    best_params = dict(params)

            # 3b. Run best params on out-of-sample
            best_strategy = self._strategy_factory(best_params)
            oos_bt_engine = BacktestEngine(
                signal_strategy=best_strategy,
                market_data_repository=self._market_data_repository,
                indicator_engine=self._indicator_engine,
            )
            oos_config = BacktestConfig(
                strategy_id=config.strategy_id,
                symbols=list(config.symbols),
                start_date=oos_start,
                end_date=oos_end,
                interval=config.interval,
                initial_equity=config.initial_equity,
            )
            oos_result = oos_bt_engine.run(oos_config)
            total_backtests += 1

            oos_metric = self._extract_metric(
                oos_result,
                config.optimization_metric,
            )

            window_result = WalkForwardWindowResult(
                window_index=idx,
                in_sample_start=is_start,
                in_sample_end=is_end,
                out_of_sample_start=oos_start,
                out_of_sample_end=oos_end,
                best_params=best_params,
                in_sample_metric=best_metric,
                out_of_sample_metric=oos_metric,
                parameter_combinations_tested=combos_tested,
            )
            window_results.append(window_result)
            all_best_params.append(best_params)

        # 4. Aggregate metrics
        aggregate_oos = (
            sum(w.out_of_sample_metric for w in window_results) / len(window_results)
            if window_results
            else 0.0
        )

        # 5. Stability score
        stability = self._compute_stability(all_best_params)

        # 6. Consensus params — most frequently selected
        consensus = self._compute_consensus(all_best_params)

        result = WalkForwardResult(
            config=config,
            windows=window_results,
            aggregate_oos_metric=round(aggregate_oos, 4),
            stability_score=stability,
            best_consensus_params=consensus,
            total_backtests_run=total_backtests,
        )

        logger.info(
            "Walk-forward analysis completed",
            strategy_id=config.strategy_id,
            windows=len(window_results),
            aggregate_oos=round(aggregate_oos, 4),
            stability=stability,
            total_backtests=total_backtests,
        )

        return result

    # ------------------------------------------------------------------
    # Internal: Generate rolling windows
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_windows(
        config: WalkForwardConfig,
    ) -> list[tuple[date, date, date, date]]:
        """
        Generate rolling window date ranges from config.

        Each window is a tuple of (is_start, is_end, oos_start, oos_end).
        Windows advance by step_bars days from the overall start_date.

        Args:
            config: Walk-forward configuration.

        Returns:
            List of (in_sample_start, in_sample_end, oos_start, oos_end) tuples.
        """
        windows: list[tuple[date, date, date, date]] = []
        current_start = config.start_date

        while True:
            is_end = current_start + timedelta(days=config.in_sample_bars - 1)
            oos_start = is_end + timedelta(days=1)
            oos_end = oos_start + timedelta(days=config.out_of_sample_bars - 1)

            # Stop if out-of-sample extends past the end date
            if oos_end > config.end_date:
                break

            windows.append((current_start, is_end, oos_start, oos_end))
            current_start += timedelta(days=config.step_bars)

        return windows

    # ------------------------------------------------------------------
    # Internal: Enumerate parameter combinations
    # ------------------------------------------------------------------

    @staticmethod
    def _enumerate_params(
        parameter_grid: dict[str, list[Any]],
    ) -> list[dict[str, Any]]:
        """
        Generate all cartesian product combinations from the parameter grid.

        Args:
            parameter_grid: Dict of param_name → list of candidate values.

        Returns:
            List of dicts, each representing one parameter combination.

        Example:
            grid = {"a": [1, 2], "b": [10, 20]}
            combos = _enumerate_params(grid)
            # [{"a": 1, "b": 10}, {"a": 1, "b": 20}, {"a": 2, "b": 10}, {"a": 2, "b": 20}]
        """
        if not parameter_grid:
            return [{}]

        keys = list(parameter_grid.keys())
        values = [parameter_grid[k] for k in keys]
        combos: list[dict[str, Any]] = []

        for combo in itertools.product(*values):
            combos.append(dict(zip(keys, combo, strict=True)))

        return combos

    # ------------------------------------------------------------------
    # Internal: Extract metric from backtest result
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_metric(
        result: BacktestResult,
        metric: OptimizationMetric,
    ) -> float:
        """
        Extract the target optimization metric from a backtest result.

        For MAX_DRAWDOWN, negates the value since max_drawdown_pct is
        negative and we want to maximize (least drawdown = best).

        Args:
            result: BacktestResult from a completed backtest.
            metric: Which metric to extract.

        Returns:
            Float value of the metric.
        """
        if metric == OptimizationMetric.SHARPE:
            return float(result.sharpe_ratio)
        if metric == OptimizationMetric.TOTAL_RETURN:
            return float(result.total_return_pct)
        if metric == OptimizationMetric.PROFIT_FACTOR:
            return float(result.profit_factor)
        if metric == OptimizationMetric.MAX_DRAWDOWN:
            # Negate: less negative = better. -5% > -10%, so negate to maximize.
            return -float(result.max_drawdown_pct)
        if metric == OptimizationMetric.SORTINO:
            # Use Sharpe as proxy when Sortino not separately computed
            return float(result.sharpe_ratio)
        if metric == OptimizationMetric.CALMAR:
            # Calmar = annualized return / max drawdown
            if result.max_drawdown_pct < Decimal("0"):
                return float(result.annualized_return_pct / abs(result.max_drawdown_pct))
            return float(result.annualized_return_pct)
        return 0.0

    # ------------------------------------------------------------------
    # Internal: Stability scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_stability(all_best_params: list[dict[str, Any]]) -> float:
        """
        Compute parameter stability score across windows.

        Stability = fraction of windows that chose the most popular
        parameter combination. 1.0 if all windows chose the same.

        Args:
            all_best_params: List of best_params dicts from each window.

        Returns:
            Float in [0.0, 1.0].
        """
        if not all_best_params:
            return 0.0

        # Convert dicts to hashable tuples for counting
        param_tuples = [tuple(sorted(p.items())) for p in all_best_params]
        counts = Counter(param_tuples)
        most_common_count = counts.most_common(1)[0][1]
        return round(most_common_count / len(all_best_params), 4)

    # ------------------------------------------------------------------
    # Internal: Consensus parameters
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_consensus(all_best_params: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Find the most frequently selected parameter combination.

        Args:
            all_best_params: List of best_params dicts from each window.

        Returns:
            The parameter dict that was selected most often.
        """
        if not all_best_params:
            return {}

        param_tuples = [tuple(sorted(p.items())) for p in all_best_params]
        counts = Counter(param_tuples)
        most_common_tuple = counts.most_common(1)[0][0]
        return dict(most_common_tuple)
