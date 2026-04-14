/**
 * Audit Explorer page wrapper — delegates to AuditExplorer feature component.
 *
 * Purpose:
 *   Route-level page component for /audit. Wraps the feature component
 *   in a FeatureErrorBoundary.
 */

import { AuditExplorer } from "@/features/audit/components/AuditExplorer";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Audit() {
  return (
    <FeatureErrorBoundary featureName="Audit Explorer">
      <AuditExplorer />
    </FeatureErrorBoundary>
  );
}
