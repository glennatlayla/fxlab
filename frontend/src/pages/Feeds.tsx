/**
 * Feeds page wrapper — delegates to the feeds feature FeedsPage component.
 *
 * Purpose:
 *   Route-level page component for /feeds. Wraps the feature in a
 *   FeatureErrorBoundary to isolate failures from the rest of the app
 *   (M29 production hardening).
 *
 * Does NOT:
 *   - Contain business logic or rendering.
 *   - Handle authentication (AuthGuard wraps this in router).
 */

import { FeedsPage } from "@/features/feeds/components/FeedsPage";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Feeds() {
  return (
    <FeatureErrorBoundary featureName="Feeds">
      <FeedsPage />
    </FeatureErrorBoundary>
  );
}
