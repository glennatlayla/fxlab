/**
 * Overrides page wrapper — delegates to OverridesPage feature component.
 *
 * Purpose:
 *   Route-level page component for /overrides. Delegates all rendering
 *   to the governance feature's OverridesPage component.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Handle authentication (AuthGuard wraps this in router).
 */

import { OverridesPage } from "@/features/governance/components/OverridesPage";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Overrides() {
  return (
    <FeatureErrorBoundary featureName="Overrides">
      <OverridesPage />
    </FeatureErrorBoundary>
  );
}
