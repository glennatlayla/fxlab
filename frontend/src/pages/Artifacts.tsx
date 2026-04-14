/**
 * Artifacts page wrapper — delegates to ArtifactBrowser feature component.
 *
 * Purpose:
 *   Route-level page component for /artifacts. Wraps the feature component
 *   in a FeatureErrorBoundary with page-level header.
 */

import { ArtifactBrowser } from "@/features/artifacts/components/ArtifactBrowser";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function Artifacts() {
  return (
    <FeatureErrorBoundary featureName="Artifact Browser">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Artifact Browser</h1>
          <p className="mt-1 text-sm text-surface-500">
            Browse, download, and manage strategy run artifacts.
          </p>
        </div>
        <ArtifactBrowser />
      </div>
    </FeatureErrorBoundary>
  );
}
