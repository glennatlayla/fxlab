/**
 * PromotionHistory component — timeline panel for strategy candidate promotions.
 *
 * Purpose:
 *   Renders a chronological timeline of all promotion requests for a given
 *   strategy candidate. Intended for display on StrategyVersionPage as a
 *   governance overview panel.
 *
 * Responsibilities:
 *   - Fetch promotion history via TanStack Query.
 *   - Render loading, empty, and error states.
 *   - Display each entry with status badge, target environment, submitter,
 *     timestamps, reviewer info, decision rationale, evidence link, and
 *     override watermark.
 *   - Sanitize evidence URLs against XSS injection.
 *
 * Does NOT:
 *   - Manage approval/reject mutations (that is ApprovalsPage).
 *   - Contain business logic beyond display.
 *
 * Dependencies:
 *   - TanStack React Query (useQuery, useQueryClient).
 *   - governanceApi.listPromotions from ../api.
 *   - Types from @/types/governance.
 *
 * Example:
 *   <PromotionHistory candidateId="01HCANDIDATE0000000001" />
 */

import { memo, useId, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { PromotionHistoryEntry } from "@/types/governance";
import { governanceApi } from "../api";
import { sanitizeUrl } from "../utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Promotion status → Tailwind badge classes. */
const PROMOTION_STATUS_CLASSES: Record<PromotionHistoryEntry["status"], string> = {
  pending: "bg-yellow-100 text-yellow-800",
  validating: "bg-blue-100 text-blue-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-red-100 text-red-800",
  deploying: "bg-indigo-100 text-indigo-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-200 text-red-900",
};

/** Promotion status → human-readable labels. */
const PROMOTION_STATUS_LABELS: Record<PromotionHistoryEntry["status"], string> = {
  pending: "Pending",
  validating: "Validating",
  approved: "Approved",
  rejected: "Rejected",
  deploying: "Deploying",
  completed: "Completed",
  failed: "Failed",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface PromotionHistoryProps {
  /** ULID of the strategy candidate to show promotion history for. */
  candidateId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * PromotionHistory panel — timeline of all promotion requests for a candidate.
 *
 * Fetches promotion history from the governance API and renders a vertical
 * timeline with status badges, metadata, and evidence links.
 */
export const PromotionHistory = memo(function PromotionHistory({
  candidateId,
}: PromotionHistoryProps) {
  const correlationId = useId();
  const queryClient = useQueryClient();

  const {
    data: promotions,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["governance", "promotions", candidateId],
    queryFn: ({ signal }) => governanceApi.listPromotions(candidateId, correlationId, signal),
  });

  const handleRetry = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["governance", "promotions", candidateId],
    });
  }, [queryClient, candidateId]);

  // -- Loading state --------------------------------------------------------
  if (isLoading) {
    return (
      <div role="status" className="p-4 text-sm text-gray-500">
        Loading promotion history…
      </div>
    );
  }

  // -- Error state ----------------------------------------------------------
  if (isError) {
    return (
      <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4">
        <p className="text-sm text-red-700">
          Failed to load promotion history
          {error instanceof Error ? `: ${error.message}` : "."}
        </p>
        <button
          onClick={handleRetry}
          className="mt-2 text-sm font-medium text-red-600 underline hover:text-red-800"
        >
          Retry
        </button>
      </div>
    );
  }

  // -- Empty state ----------------------------------------------------------
  if (!promotions || promotions.length === 0) {
    return (
      <div className="p-4 text-sm text-gray-500">No promotion requests for this candidate.</div>
    );
  }

  // -- Timeline -------------------------------------------------------------
  return (
    <section aria-label="Promotion History">
      <h3 className="mb-4 text-sm font-semibold text-gray-900">Promotion History</h3>
      <ol className="relative border-l border-gray-200">
        {promotions.map((entry) => (
          <PromotionTimelineEntry key={entry.id} entry={entry} />
        ))}
      </ol>
    </section>
  );
});

// ---------------------------------------------------------------------------
// Timeline entry sub-component
// ---------------------------------------------------------------------------

interface PromotionTimelineEntryProps {
  entry: PromotionHistoryEntry;
}

const PromotionTimelineEntry = memo(function PromotionTimelineEntry({
  entry,
}: PromotionTimelineEntryProps) {
  const safeEvidenceUrl = entry.evidence_link ? sanitizeUrl(entry.evidence_link) : null;

  return (
    <li data-testid={`promotion-entry-${entry.id}`} className="mb-6 ml-4">
      {/* Timeline dot */}
      <div className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-white bg-gray-300" />

      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        {/* Header: status badge + environment */}
        <div className="mb-2 flex items-center gap-2">
          <span
            className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${PROMOTION_STATUS_CLASSES[entry.status]}`}
          >
            {PROMOTION_STATUS_LABELS[entry.status]}
          </span>
          <span className="text-xs font-medium text-gray-600">{entry.target_environment}</span>
        </div>

        {/* Metadata */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
          <dt className="font-medium">Submitted by</dt>
          <dd>{entry.submitted_by}</dd>

          <dt className="font-medium">Created</dt>
          <dd>{new Date(entry.created_at).toISOString().slice(0, 10)}</dd>

          {entry.reviewed_by && (
            <>
              <dt className="font-medium">Reviewed by</dt>
              <dd>{entry.reviewed_by}</dd>
            </>
          )}

          {entry.reviewed_at && (
            <>
              <dt className="font-medium">Reviewed at</dt>
              <dd>{new Date(entry.reviewed_at).toISOString().slice(0, 10)}</dd>
            </>
          )}
        </dl>

        {/* Decision rationale */}
        {entry.decision_rationale && (
          <div data-testid="promotion-rationale" className="mt-2">
            <p className="text-xs font-medium text-gray-600">Rationale</p>
            <p className="text-sm text-gray-800">{entry.decision_rationale}</p>
          </div>
        )}

        {/* Evidence link */}
        {safeEvidenceUrl && (
          <div className="mt-2">
            <a
              href={safeEvidenceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-blue-600 underline hover:text-blue-800"
            >
              Evidence link
            </a>
          </div>
        )}

        {/* Override watermark */}
        {entry.override_watermark && (
          <div
            data-testid="promotion-watermark"
            className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800"
          >
            <span className="font-medium">Override watermark: </span>
            {JSON.stringify(entry.override_watermark)}
          </div>
        )}
      </div>
    </li>
  );
});
