/**
 * RegimeConsistencyTable — per-regime Sharpe with pass/fail indicators.
 *
 * Purpose:
 *   Display regime consistency results showing which regimes have
 *   positive Sharpe ratios.
 *
 * Responsibilities:
 *   - Render a table row per regime with Sharpe and pass/fail.
 *   - Display trade count per regime.
 *   - Handle empty state.
 *
 * Does NOT:
 *   - Compute regime metrics (backend-authoritative).
 *   - Fetch data.
 *
 * Dependencies:
 *   - RegimeConsistencyTableProps from ../types.
 *
 * Example:
 *   <RegimeConsistencyTable entries={payload.regime_consistency} />
 */

import { memo } from "react";
import type { RegimeConsistencyTableProps } from "../types";

/**
 * Render the regime consistency table.
 *
 * Args:
 *   entries: Per-regime consistency entries.
 *
 * Returns:
 *   Table element or empty state.
 */
export const RegimeConsistencyTable = memo(function RegimeConsistencyTable({
  entries,
}: RegimeConsistencyTableProps) {
  if (entries.length === 0) {
    return (
      <div
        data-testid="regime-consistency-empty"
        className="flex h-20 items-center justify-center text-sm text-slate-400"
      >
        No regime data available.
      </div>
    );
  }

  return (
    <div data-testid="regime-consistency-table" className="space-y-2">
      <h4 className="text-sm font-semibold text-slate-700">Regime Consistency</h4>
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <caption className="sr-only">Regime consistency evaluation results</caption>
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-slate-600">Regime</th>
              <th className="px-4 py-2 text-right font-medium text-slate-600">Sharpe</th>
              <th className="px-4 py-2 text-right font-medium text-slate-600">Trades</th>
              <th className="px-4 py-2 text-center font-medium text-slate-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {entries.map((entry) => (
              <tr
                key={entry.regime}
                data-testid={`regime-row-${entry.regime}`}
                data-passed={String(entry.passed)}
                className="hover:bg-slate-50"
              >
                <td className="px-4 py-2 font-medium capitalize text-slate-700">{entry.regime}</td>
                <td
                  className={`px-4 py-2 text-right tabular-nums ${
                    entry.sharpe_ratio >= 0 ? "text-emerald-600" : "text-red-600"
                  }`}
                >
                  {entry.sharpe_ratio.toFixed(2)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-slate-600">
                  {entry.trade_count}
                </td>
                <td className="px-4 py-2 text-center">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                      entry.passed ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
                    }`}
                  >
                    {entry.passed ? "Pass" : "Fail"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});
