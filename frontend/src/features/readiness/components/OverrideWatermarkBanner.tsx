/**
 * OverrideWatermarkBanner — amber watermark for active governance overrides.
 *
 * Purpose:
 *   Display a prominent banner when an active override applies to the
 *   readiness report, per spec §8.2.
 *
 * Responsibilities:
 *   - Render override type, rationale, and evidence link.
 *   - Apply amber styling for visibility.
 *   - Evidence link opens in new tab with security attributes.
 *
 * Does NOT:
 *   - Manage override lifecycle (parent/backend decides).
 *   - Render when watermark is null (parent gates rendering).
 *
 * Dependencies:
 *   - OverrideWatermarkBannerProps from ../types.
 *   - OVERRIDE_WATERMARK_CLASSES from ../constants.
 *
 * Example:
 *   {watermark && <OverrideWatermarkBanner watermark={watermark} />}
 */

import { memo } from "react";
import type { OverrideWatermarkBannerProps } from "../types";
import { OVERRIDE_WATERMARK_CLASSES } from "../constants";

/** Format override type for display. */
function formatOverrideType(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * Sanitize a URL to prevent javascript: protocol injection.
 * Only allows http: and https: protocols.
 *
 * Args:
 *   url: The URL string to sanitize.
 *
 * Returns:
 *   The original URL if safe, or undefined if potentially dangerous.
 */
function sanitizeUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return url;
    }
    return undefined;
  } catch {
    // Relative URLs or malformed — reject them for external links.
    return undefined;
  }
}

/**
 * Render the override watermark banner.
 *
 * Args:
 *   watermark: Override watermark metadata.
 *
 * Returns:
 *   Banner element with amber styling and override details.
 */
export const OverrideWatermarkBanner = memo(function OverrideWatermarkBanner({
  watermark,
}: OverrideWatermarkBannerProps) {
  return (
    <div
      data-testid="override-watermark-banner"
      role="alert"
      className={`rounded-lg border border-amber-300 p-4 ring-1 ring-inset ${OVERRIDE_WATERMARK_CLASSES}`}
    >
      <div className="flex items-center gap-2">
        <svg
          className="h-5 w-5 text-amber-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
        </svg>
        <span className="text-sm font-semibold">
          Active Override: {formatOverrideType(watermark.override_type)}
        </span>
      </div>

      <p className="mt-2 text-sm">{watermark.rationale}</p>

      <div className="mt-2 flex items-center gap-4 text-xs">
        {watermark.evidence_link && sanitizeUrl(watermark.evidence_link) && (
          <a
            href={sanitizeUrl(watermark.evidence_link)}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-amber-700 underline hover:text-amber-900"
            aria-label="Evidence link"
          >
            View Evidence
          </a>
        )}
        <span className="text-amber-600">
          Created: {new Date(watermark.created_at).toLocaleDateString()}
        </span>
      </div>
    </div>
  );
});
