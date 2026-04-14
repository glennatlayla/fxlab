/**
 * Queues page wrapper — delegates to QueuesPage feature component.
 *
 * Purpose:
 *   Route-level page component for /queues. Wraps the feature component
 *   in a FeatureErrorBoundary.
 */

import { QueuesPage } from "@/features/queues/components/QueuesPage";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Queues() {
  return (
    <FeatureErrorBoundary featureName="Queue Dashboard">
      <QueuesPage />
    </FeatureErrorBoundary>
  );
}
