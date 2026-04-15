/**
 * RunReadiness page — M28 Readiness Report Viewer route wrapper.
 *
 * Purpose:
 *   Top-level page component for the /runs/:runId/readiness route.
 *   Extracts the runId URL parameter and delegates rendering to
 *   the RunReadinessPage feature component.
 *
 * Responsibilities:
 *   - Extract runId from URL params.
 *   - Show error state when runId is missing.
 *   - Delegate all readiness logic to RunReadinessPage.
 *
 * Does NOT:
 *   - Contain readiness business logic.
 *   - Fetch readiness data directly.
 *
 * Dependencies:
 *   - useParams from react-router-dom.
 *   - RunReadinessPage from @/features/readiness.
 */

import { useParams } from "react-router-dom";
import { RunReadinessPage } from "@/features/readiness/components/RunReadinessPage";

export default function RunReadiness() {
  const { runId } = useParams<{ runId: string }>();

  if (!runId) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6" role="alert">
        <h2 className="text-lg font-semibold text-red-800">Missing Run ID</h2>
        <p className="mt-2 text-sm text-red-700">
          No run ID was provided. Please navigate to a specific run to view its readiness report.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Readiness Report</h1>
        <p className="mt-1 text-sm text-slate-500">
          Run <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs">{runId}</code>
        </p>
      </div>
      <RunReadinessPage runId={runId} />
    </div>
  );
}
