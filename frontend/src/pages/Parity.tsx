/**
 * Parity page wrapper — delegates to ParityPage feature component.
 *
 * Purpose:
 *   Route-level page component for /parity. Wraps the feature component
 *   in a FeatureErrorBoundary.
 */

import { ParityPage } from "@/features/parity/components/ParityPage";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Parity() {
  return (
    <FeatureErrorBoundary featureName="Parity Dashboard">
      <ParityPage />
    </FeatureErrorBoundary>
  );
}
