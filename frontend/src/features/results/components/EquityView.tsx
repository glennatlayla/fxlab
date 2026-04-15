/**
 * EquityView — composite equity + drawdown + overlays container.
 *
 * Purpose:
 *   Composes the EquityCurve and DrawdownCurve charts into a single
 *   section with shared fold-boundary and regime-segment overlays.
 *
 * Responsibilities:
 *   - Render EquityCurve with fold boundaries and regime segments.
 *   - Render DrawdownCurve below the equity chart.
 *   - Pass the correct engine prop to both charts.
 *
 * Does NOT:
 *   - Fetch data (receives RunChartsPayload as a prop).
 *   - Handle banners or tables.
 *
 * Dependencies:
 *   - EquityViewProps from ../types.
 *   - EquityCurve, DrawdownCurve child components.
 */

import { memo } from "react";
import type { EquityViewProps } from "../types";
import { EquityCurve } from "./EquityCurve";
import { DrawdownCurve } from "./DrawdownCurve";

/**
 * Render the equity view container.
 *
 * Args:
 *   data: Full RunChartsPayload.
 *   engine: Chart rendering engine ("recharts" or "echarts").
 *
 * Returns:
 *   Container element with equity and drawdown charts.
 */
export const EquityView = memo(function EquityView({ data, engine }: EquityViewProps) {
  return (
    <div data-testid="equity-view" className="space-y-4">
      <EquityCurve
        data={data.equity_curve}
        engine={engine}
        foldBoundaries={data.fold_boundaries}
        regimeSegments={data.regime_segments}
      />
      <DrawdownCurve data={data.equity_curve} engine={engine} />
    </div>
  );
});
