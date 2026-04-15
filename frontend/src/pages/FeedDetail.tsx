/**
 * FeedDetail page wrapper — delegates to FeedDetailPage with the routed feedId.
 *
 * Purpose:
 *   Route-level page component for /feeds/:feedId. Resolves the route param
 *   and forwards it to the feature component, wrapped in a FeatureErrorBoundary.
 */

import { useParams } from "react-router-dom";
import { FeedDetailPage } from "@/features/feeds/components/FeedDetailPage";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";

export default function FeedDetail() {
  const { feedId } = useParams<{ feedId: string }>();
  return (
    <FeatureErrorBoundary featureName="Feed Detail">
      {feedId ? (
        <FeedDetailPage feedId={feedId} />
      ) : (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Missing feed identifier in URL.
        </div>
      )}
    </FeatureErrorBoundary>
  );
}
