/**
 * OverrideViewer — display override detail with evidence link, status, and watermark.
 *
 * Purpose:
 *   Render the full detail of a governance override including evidence link
 *   as a clickable external link (AC-5), ACTIVE/revoked status (AC-7),
 *   decision rationale, and revocation history.
 *
 * Responsibilities:
 *   - Display override metadata (type, object, submitter, dates).
 *   - Render evidence_link as clickable <a target="_blank"> (AC-5).
 *   - Show ACTIVE status badge for approved overrides, muted "revoked" for rejected.
 *   - Display original_state → new_state diff.
 *   - Sanitize evidence_link URL against XSS (http/https only).
 *
 * Does NOT:
 *   - Fetch override data (parent provides it).
 *   - Execute mutations.
 *
 * Dependencies:
 *   - OverrideDetail type from @/types/governance.
 *   - Constants for styling.
 *
 * Example:
 *   <OverrideViewer override={overrideDetail} />
 */

import { memo } from "react";
import type { OverrideDetail } from "@/types/governance";
import { STATUS_BADGE_CLASSES, STATUS_LABELS, OVERRIDE_TYPE_LABELS } from "../constants";
import { sanitizeUrl } from "../utils";

export interface OverrideViewerProps {
  /** The override detail to display. */
  override: OverrideDetail;
}

/**
 * Render override detail with evidence link and status.
 */
export const OverrideViewer = memo(function OverrideViewer({ override }: OverrideViewerProps) {
  const safeEvidenceUrl = sanitizeUrl(override.evidence_link);

  // AC-7: ACTIVE for approved, muted "revoked" for rejected.
  const statusDisplay =
    override.status === "approved" ? (
      <span
        data-testid="override-status-active"
        className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-emerald-800 ring-1 ring-inset ring-emerald-600/20"
      >
        Active
      </span>
    ) : override.status === "rejected" ? (
      <span
        data-testid="override-status-revoked"
        className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500 ring-1 ring-inset ring-slate-300"
      >
        revoked
      </span>
    ) : (
      <span
        data-testid="override-status-pending"
        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_BADGE_CLASSES[override.status]}`}
      >
        {STATUS_LABELS[override.status]}
      </span>
    );

  return (
    <div data-testid={`override-viewer-${override.id}`} className="space-y-4">
      {/* Header: type + status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-slate-700">
            {OVERRIDE_TYPE_LABELS[override.override_type] ?? override.override_type}
          </span>
          {statusDisplay}
        </div>
        <span className="text-xs text-slate-400">
          {new Date(override.created_at).toLocaleString()}
        </span>
      </div>

      {/* Metadata */}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="font-medium text-slate-600">Object</dt>
        <dd className="text-slate-900">
          {override.object_type} / {override.object_id}
        </dd>

        <dt className="font-medium text-slate-600">Submitted by</dt>
        <dd data-testid="override-submitter" className="text-slate-900">
          {override.submitter_id}
        </dd>

        {override.reviewed_by && (
          <>
            <dt className="font-medium text-slate-600">Reviewed by</dt>
            <dd data-testid="override-reviewer" className="text-slate-900">
              {override.reviewed_by}
            </dd>
          </>
        )}

        {override.reviewed_at && (
          <>
            <dt className="font-medium text-slate-600">Reviewed at</dt>
            <dd className="text-slate-900">{new Date(override.reviewed_at).toLocaleString()}</dd>
          </>
        )}
      </dl>

      {/* Rationale */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
        <p className="font-medium text-slate-600">Rationale</p>
        <p data-testid="override-rationale" className="mt-1 text-slate-700">
          {override.rationale}
        </p>
      </div>

      {/* Evidence link (AC-5: clickable external link) */}
      {safeEvidenceUrl && (
        <div className="text-sm">
          <span className="font-medium text-slate-600">Evidence: </span>
          <a
            href={safeEvidenceUrl}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="override-evidence-link"
            className="text-blue-600 underline hover:text-blue-800"
          >
            {safeEvidenceUrl}
          </a>
        </div>
      )}

      {/* State diff */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="mb-1 font-medium text-slate-600">Original State</p>
          <pre
            data-testid="override-original-state"
            className="overflow-x-auto text-xs text-slate-700"
          >
            {JSON.stringify(override.original_state, null, 2)}
          </pre>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="mb-1 font-medium text-slate-600">New State</p>
          <pre data-testid="override-new-state" className="overflow-x-auto text-xs text-slate-700">
            {JSON.stringify(override.new_state, null, 2)}
          </pre>
        </div>
      </div>

      {/* Override watermark info */}
      {override.override_watermark && (
        <div
          data-testid="override-watermark-detail"
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          <p className="font-medium">Override Watermark Active</p>
          <pre className="mt-1 overflow-x-auto text-xs">
            {JSON.stringify(override.override_watermark, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
});
