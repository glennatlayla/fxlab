/**
 * Component prop interfaces for the Results Explorer feature (M27).
 *
 * Purpose:
 *   Define strongly-typed props for all Results Explorer components.
 *   Each interface maps 1:1 to a React component in ./components/.
 *
 * Does NOT:
 *   - Contain implementation or rendering logic.
 *   - Contain API or domain types (those are in @/types/results.ts).
 *
 * Dependencies:
 *   - @/types/results for domain types.
 */

import type {
  EquityPoint,
  FoldBoundary,
  RegimeSegment,
  TradeRecord,
  SegmentPerformance,
  TrialSummary,
  CandidateMetrics,
  TradeBlotterFilters,
  RunChartsPayload,
} from "@/types/results";
import type { ChartEngine } from "@/hooks/useChartEngine";

// ---------------------------------------------------------------------------
// Page-level
// ---------------------------------------------------------------------------

/** Props for the RunResultsPage container. */
export interface RunResultsPageProps {
  /** Run ID from the route parameter. */
  runId: string;
}

// ---------------------------------------------------------------------------
// Chart components
// ---------------------------------------------------------------------------

/** Props for the EquityCurve chart component. */
export interface EquityCurveProps {
  /** Equity data points. */
  data: EquityPoint[];
  /** Chart rendering engine to use. */
  engine: ChartEngine;
  /** Walk-forward fold boundaries (optional overlays). */
  foldBoundaries?: FoldBoundary[];
  /** Regime color bands (optional overlays). */
  regimeSegments?: RegimeSegment[];
}

/** Props for the DrawdownCurve chart component. */
export interface DrawdownCurveProps {
  /** Equity data points (drawdown field used). */
  data: EquityPoint[];
  /** Chart rendering engine to use. */
  engine: ChartEngine;
}

/** Props for the SegmentedPerformanceBar chart. */
export interface SegmentedPerformanceBarProps {
  /** Per-fold performance data. */
  foldPerformance: SegmentPerformance[];
  /** Per-regime performance data. */
  regimePerformance: SegmentPerformance[];
}

/** Props for the RegimeOverlay on the equity chart. */
export interface RegimeOverlayProps {
  /** Regime segments to render as color bands. */
  segments: RegimeSegment[];
  /** Chart width in pixels (for scaling). */
  chartWidth: number;
  /** Earliest timestamp in the equity curve. */
  startTimestamp: string;
  /** Latest timestamp in the equity curve. */
  endTimestamp: string;
}

// ---------------------------------------------------------------------------
// Table components
// ---------------------------------------------------------------------------

/** Props for the TradeBlotter component. */
export interface TradeBlotterProps {
  /** Trade records to display. */
  trades: TradeRecord[];
  /** Whether the trade list was truncated by the backend. */
  tradesTruncated: boolean;
  /** Total trade count before truncation. */
  totalTradeCount: number;
  /** Current filter state. */
  filters: TradeBlotterFilters;
  /** Callback when filters change. */
  onFiltersChange: (filters: TradeBlotterFilters) => void;
  /** Callback to trigger data export. */
  onDownload: () => void;
  /** Whether a download is currently in progress. */
  isDownloading?: boolean;
}

/** Props for the TrialSummaryTable component. */
export interface TrialSummaryTableProps {
  /** Trial summary rows. */
  trials: TrialSummary[];
  /** Number of top trials to highlight. */
  topN: number;
  /** Callback when a trial row is clicked. */
  onTrialClick: (trialId: string) => void;
  /** Callback to trigger data export. */
  onDownload: () => void;
  /** Whether a download is currently in progress. */
  isDownloading?: boolean;
}

/** Props for the CandidateComparisonTable component. */
export interface CandidateComparisonTableProps {
  /** Candidate metrics for side-by-side comparison. */
  candidates: CandidateMetrics[];
  /** Callback to trigger data export. */
  onDownload: () => void;
  /** Whether a download is currently in progress. */
  isDownloading?: boolean;
}

// ---------------------------------------------------------------------------
// Banner components
// ---------------------------------------------------------------------------

/** Props for the SamplingBanner component. */
export interface SamplingBannerProps {
  /** Whether LTTB sampling was applied. */
  samplingApplied: boolean;
  /** Original point count before downsampling. */
  rawPointCount: number;
  /** Current displayed point count. */
  displayedPointCount: number;
}

/** Props for the TradesTruncatedBanner component. */
export interface TradesTruncatedBannerProps {
  /** Whether trades were truncated. */
  tradesTruncated: boolean;
  /** Total trade count before truncation. */
  totalTradeCount: number;
  /** Callback to trigger full dataset download. */
  onDownload: () => void;
}

// ---------------------------------------------------------------------------
// Download button
// ---------------------------------------------------------------------------

/** Props for the DownloadDataButton component. */
export interface DownloadDataButtonProps {
  /** Callback to trigger download. */
  onDownload: () => void;
  /** Button label text. */
  label?: string;
  /** Whether the download is in progress. */
  isLoading?: boolean;
}

// ---------------------------------------------------------------------------
// EquityView (composite component)
// ---------------------------------------------------------------------------

/** Props for the EquityView container that houses equity + drawdown + overlays. */
export interface EquityViewProps {
  /** Full charts payload. */
  data: RunChartsPayload;
  /** Chart rendering engine. */
  engine: ChartEngine;
}
