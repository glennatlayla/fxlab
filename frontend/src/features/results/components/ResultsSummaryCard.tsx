/**
 * ResultsSummaryCard — mobile-optimized results summary view.
 *
 * Purpose:
 *   Display key performance metrics (Sharpe ratio, total return, max drawdown,
 *   win rate, trade count, profit factor) for a completed run in a compact
 *   mobile-friendly card layout. Fetches data via resultsApi and uses
 *   @tanstack/react-query for caching and error handling.
 *
 * Responsibilities:
 *   - Fetch run charts data via resultsApi.getRunCharts().
 *   - Calculate key metrics from equity curve and trade data.
 *   - Color-code metrics based on performance sentiment.
 *   - Display loading skeleton while fetching.
 *   - Show error state with retry capability.
 *   - Render "View Full Results" button if onViewFull callback provided.
 *
 * Does NOT:
 *   - Render detailed charts (that's RunResultsPage).
 *   - Manage navigation (parent component handles routing).
 *   - Store state outside React (useQuery handles cache).
 *
 * Dependencies:
 *   - @tanstack/react-query (useQuery).
 *   - resultsApi from ./api.
 *   - ResultsMetricTile component.
 *   - lucide-react icons.
 *
 * Error conditions:
 *   - API returns 404: shows "Run not found" error.
 *   - API returns 401/403: shows "Access denied" error.
 *   - Network error: shows retry button.
 *   - Schema validation error: shows generic error.
 *
 * Example:
 *   <ResultsSummaryCard
 *     runId="01HRUN..."
 *     onViewFull={() => navigate("/results/...")}
 *   />
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, BarChart3, Target, Package, AlertCircle } from "lucide-react";
import { resultsApi } from "../api";
import { ResultsMetricTile } from "./ResultsMetricTile";

/**
 * Props for the ResultsSummaryCard component.
 */
export interface ResultsSummaryCardProps {
  /** Run ID to fetch results for. */
  runId: string;
  /** Optional callback when user wants to see full results. */
  onViewFull?: () => void;
}

/**
 * Calculate sentiment for Sharpe ratio.
 *
 * Args:
 *   sharpeRatio: The Sharpe ratio value.
 *
 * Returns:
 *   Sentiment: "positive" (>1.5), "warning" (0.5-1.5), or "negative" (<0.5).
 */
function getSharpeRatioSentiment(sharpeRatio: number): "positive" | "warning" | "negative" {
  if (sharpeRatio > 1.5) return "positive";
  if (sharpeRatio >= 0.5) return "warning";
  return "negative";
}

/**
 * Calculate total return percentage from equity curve.
 *
 * Args:
 *   equityCurve: Array of equity points.
 *
 * Returns:
 *   Percentage return (e.g., 2.5 for +2.5%).
 */
function calculateTotalReturn(equityCurve: Array<{ equity: number }>): number {
  if (equityCurve.length < 2) return 0;
  const startEquity = equityCurve[0].equity;
  const endEquity = equityCurve[equityCurve.length - 1].equity;
  return ((endEquity - startEquity) / startEquity) * 100;
}

/**
 * Calculate maximum drawdown from equity curve.
 *
 * Args:
 *   equityCurve: Array of equity points (should include drawdown field).
 *
 * Returns:
 *   Drawdown as negative percentage (e.g., -15.5 for 15.5% drawdown).
 */
function calculateMaxDrawdown(equityCurve: Array<{ drawdown: number }>): number {
  if (equityCurve.length === 0) return 0;
  return Math.min(...equityCurve.map((p) => p.drawdown));
}

/**
 * Calculate win rate from trades.
 *
 * Args:
 *   trades: Array of trade records with pnl field.
 *
 * Returns:
 *   Win rate as percentage (0-100), or 0 if no trades.
 */
function calculateWinRate(
  trades: Array<{
    pnl: number;
  }>,
): number {
  if (trades.length === 0) return 0;
  const wins = trades.filter((t) => t.pnl > 0).length;
  return (wins / trades.length) * 100;
}

/**
 * Calculate profit factor from trades.
 *
 * Args:
 *   trades: Array of trade records with pnl field.
 *
 * Returns:
 *   Profit factor (gross profit / gross loss), or 0 if no losing trades.
 */
function calculateProfitFactor(
  trades: Array<{
    pnl: number;
  }>,
): number {
  if (trades.length === 0) return 0;
  const grossProfit = trades.reduce((sum, t) => (t.pnl > 0 ? sum + t.pnl : sum), 0);
  const grossLoss = trades.reduce((sum, t) => (t.pnl < 0 ? sum + Math.abs(t.pnl) : sum), 0);
  if (grossLoss === 0) return grossProfit > 0 ? Infinity : 0;
  return grossProfit / grossLoss;
}

/**
 * Render loading skeleton.
 */
function ResultsSummarySkeleton() {
  return (
    <div
      className="space-y-3 rounded-lg border border-surface-700 bg-surface-800 p-4"
      data-testid="results-summary-skeleton"
    >
      <div className="h-5 w-32 animate-pulse rounded bg-surface-700" />
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-md bg-surface-700" />
        ))}
      </div>
    </div>
  );
}

/**
 * Render error state.
 *
 * Args:
 *   error: Error object or message.
 *   onRetry: Callback to retry the query.
 */
function ResultsSummaryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const errorMessage =
    error instanceof Error ? error.message : "Failed to load results. Please try again.";

  return (
    <div
      className="rounded-lg border border-red-800 bg-red-900/20 p-4"
      data-testid="results-summary-error"
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-400" aria-hidden="true" />
        <div className="flex-1">
          <p className="text-sm font-medium text-red-400">Failed to load results</p>
          <p className="mt-1 text-xs text-red-300/80">{errorMessage}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-md bg-red-800 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Render the results summary card.
 *
 * Args:
 *   runId: ULID of the run to fetch results for.
 *   onViewFull: Optional callback for "View Full Results" button.
 *
 * Returns:
 *   Card component with metrics or loading/error state.
 */
export function ResultsSummaryCard({ runId, onViewFull }: ResultsSummaryCardProps) {
  const {
    data: charts,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["results", runId],
    queryFn: () => resultsApi.getRunCharts(runId),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Calculate metrics from fetched data
  const metrics = useMemo(() => {
    if (!charts) return null;

    const totalReturn = calculateTotalReturn(charts.equity_curve);
    const maxDrawdown = calculateMaxDrawdown(charts.equity_curve);
    const winRate = calculateWinRate(charts.trades);
    const profitFactor = calculateProfitFactor(charts.trades);

    // Use best trial's Sharpe ratio, or 0 if no trials
    const bestTrial =
      charts.trial_summaries.length > 0
        ? charts.trial_summaries.reduce((prev, current) =>
            prev.sharpe_ratio > current.sharpe_ratio ? prev : current,
          )
        : { sharpe_ratio: 0 };

    return {
      totalReturn,
      maxDrawdown,
      winRate,
      profitFactor,
      sharpeRatio: bestTrial.sharpe_ratio,
      tradeCount: charts.trades.length,
    };
  }, [charts]);

  // Loading state
  if (isLoading) {
    return <ResultsSummarySkeleton />;
  }

  // Error state
  if (error || !metrics) {
    return <ResultsSummaryError error={error || "Unknown error"} onRetry={() => refetch()} />;
  }

  // Determine sentiment for each metric
  const totalReturnSentiment: "positive" | "negative" =
    metrics.totalReturn >= 0 ? "positive" : "negative";
  const sharpeSentiment = getSharpeRatioSentiment(metrics.sharpeRatio);
  const winRateSentiment: "positive" | "negative" = metrics.winRate > 50 ? "positive" : "negative";
  const profitFactorSentiment: "positive" | "negative" =
    metrics.profitFactor >= 1 ? "positive" : "negative";

  return (
    <div className="rounded-lg border border-surface-700 bg-surface-800 p-4">
      {/* Header */}
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-surface-300">
        <BarChart3 className="h-4 w-4" aria-hidden="true" />
        Results Summary
      </h2>

      {/* Metrics grid (2 columns for mobile) */}
      <div className="grid grid-cols-2 gap-3">
        <ResultsMetricTile
          label="Total Return"
          value={`${metrics.totalReturn >= 0 ? "+" : ""}${metrics.totalReturn.toFixed(2)}%`}
          sentiment={totalReturnSentiment}
          icon={metrics.totalReturn >= 0 ? TrendingUp : TrendingDown}
        />

        <ResultsMetricTile
          label="Sharpe Ratio"
          value={metrics.sharpeRatio.toFixed(2)}
          sentiment={sharpeSentiment}
          icon={Target}
        />

        <ResultsMetricTile
          label="Max Drawdown"
          value={`${metrics.maxDrawdown.toFixed(2)}%`}
          sentiment="negative"
          icon={TrendingDown}
        />

        <ResultsMetricTile
          label="Win Rate"
          value={`${metrics.winRate.toFixed(1)}%`}
          sentiment={winRateSentiment}
          icon={Package}
        />

        <ResultsMetricTile
          label="Total Trades"
          value={String(metrics.tradeCount)}
          sentiment="neutral"
        />

        <ResultsMetricTile
          label="Profit Factor"
          value={metrics.profitFactor === Infinity ? "∞" : metrics.profitFactor.toFixed(2)}
          sentiment={profitFactorSentiment}
          icon={metrics.profitFactor >= 1 ? TrendingUp : TrendingDown}
        />
      </div>

      {/* View Full Results button */}
      {onViewFull && (
        <button
          type="button"
          onClick={onViewFull}
          className="mt-4 w-full rounded-md bg-blue-700 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
        >
          View Full Results
        </button>
      )}
    </div>
  );
}
