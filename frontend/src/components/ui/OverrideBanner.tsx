/**
 * OverrideBanner — alert banner for active overrides on an entity.
 *
 * Displays a warning-style banner when a governance override is active,
 * showing the override type, submitter, and link to review.
 *
 * Example:
 *   <OverrideBanner overrideType="grade_override" submitter="jane@fxlab.io" overrideId="01H..." />
 */

import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";

interface OverrideBannerProps {
  overrideType: string;
  submitter: string;
  overrideId: string;
}

export function OverrideBanner({ overrideType, submitter, overrideId }: OverrideBannerProps) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-warning/30 bg-yellow-50 px-4 py-3">
      <AlertTriangle className="h-5 w-5 flex-shrink-0 text-warning" />
      <div className="flex-1 text-sm">
        <span className="font-medium text-yellow-800">Active override:</span>{" "}
        <span className="text-yellow-700">
          {overrideType.replace(/_/g, " ")} by {submitter}
        </span>
      </div>
      <Link
        to={`/overrides/${overrideId}`}
        className="text-sm font-medium text-yellow-700 underline hover:text-yellow-800"
      >
        Review
      </Link>
    </div>
  );
}
