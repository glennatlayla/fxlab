/**
 * Approvals page wrapper — delegates to ApprovalsPage feature component.
 *
 * Purpose:
 *   Route-level page component for /approvals. Delegates all rendering
 *   to the governance feature's ApprovalsPage component.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Handle authentication (AuthGuard wraps this in router).
 */

import { ApprovalsPage } from "@/features/governance/components/ApprovalsPage";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Approvals() {
  return (
    <FeatureErrorBoundary featureName="Approvals">
      <ApprovalsPage />
    </FeatureErrorBoundary>
  );
}
