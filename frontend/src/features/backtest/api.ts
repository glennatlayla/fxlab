/**
 * Backtest API client for FE-08 Mobile Backtest Setup.
 *
 * Purpose:
 *   Encapsulate all backtest-related API calls (research run submission).
 *   Wires to POST /runs/research endpoint for backtest execution.
 *
 * Responsibilities:
 *   - Submit backtest configuration to backend via runsApi.submitResearchRun.
 *   - Transform form values into ResearchRunSubmission payload.
 *   - Handle API errors and timeouts.
 *   - Return RunRecord on successful submission.
 *
 * Does NOT:
 *   - Manage form state or component logic.
 *   - Handle polling or run monitoring (see runs/api.ts).
 *   - Contain business logic beyond payload transformation.
 *
 * Dependencies:
 *   - @/features/runs/api (runsApi.submitResearchRun).
 *   - @/types/run (ResearchRunSubmission, RunRecord).
 *   - ./types (BacktestFormValues).
 *
 * Error conditions:
 *   - Network errors → AxiosError thrown to caller.
 *   - 422 validation error → AxiosError with details.
 *   - Timeout after 30s → AxiosError.
 *
 * Example:
 *   const formValues: BacktestFormValues = { ... };
 *   const run = await backtestApi.submitBacktest(formValues);
 */

import { runsApi } from "@/features/runs/api";
import type { BacktestFormValues } from "./types";
import type { RunRecord } from "@/types/run";

/**
 * Backtest API service.
 *
 * Currently wraps runsApi.submitResearchRun with backtest-specific
 * payload transformation. Extensible for future backtest-specific endpoints.
 */
export const backtestApi = {
  /**
   * Submit a backtest (research run) for execution.
   *
   * Transforms backtest form values into a ResearchRunSubmission payload
   * and submits via the runs API. Returns the created run record with
   * initial status "pending".
   *
   * Args:
   *   formValues: Validated backtest form data (should pass validateBacktestForm first).
   *
   * Returns:
   *   RunRecord for the newly created backtest run.
   *   Status will be "pending"; use useRunPolling to monitor progress.
   *
   * Raises:
   *   AxiosError on network failure, 422 validation error, or timeout (30s).
   *
   * Example:
   *   const run = await backtestApi.submitBacktest({
   *     strategy_build_id: "abc123",
   *     symbols: ["AAPL"],
   *     start_date: "2024-01-01",
   *     end_date: "2024-12-31",
   *     interval: "1d",
   *     initial_equity: 10000,
   *   });
   *   console.log(run.id); // Navigate to /runs/{run.id}
   */
  async submitBacktest(formValues: BacktestFormValues): Promise<RunRecord> {
    // Transform form values into research run config.
    const payload = {
      strategy_build_id: formValues.strategy_build_id,
      config: {
        symbols: formValues.symbols,
        start_date: formValues.start_date,
        end_date: formValues.end_date,
        interval: formValues.interval,
        initial_equity: formValues.initial_equity,
        ...(formValues.commission_rate !== undefined && {
          commission_rate: formValues.commission_rate,
        }),
        ...(formValues.slippage_bps !== undefined && {
          slippage_bps: formValues.slippage_bps,
        }),
      },
    };

    // Submit via the shared runs API.
    return await runsApi.submitResearchRun(payload);
  },
};
