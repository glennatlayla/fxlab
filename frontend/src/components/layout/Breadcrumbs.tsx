/**
 * Breadcrumbs component — auto-generated from current route path.
 *
 * Renders the current URL as a navigable breadcrumb trail.
 * Converts slugs like "strategy-studio" to "Strategy Studio".
 */

import { Link, useLocation } from "react-router-dom";
import { ChevronRight } from "lucide-react";

function formatSegment(segment: string): string {
  return segment
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function Breadcrumbs() {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);

  if (segments.length === 0) {
    return <h1 className="text-lg font-semibold text-surface-900">Dashboard</h1>;
  }

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm">
      <Link to="/" className="text-surface-400 hover:text-surface-600">
        Home
      </Link>
      {segments.map((segment, idx) => {
        const path = "/" + segments.slice(0, idx + 1).join("/");
        const isLast = idx === segments.length - 1;

        return (
          <span key={path} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3 text-surface-300" />
            {isLast ? (
              <span className="font-medium text-surface-900">{formatSegment(segment)}</span>
            ) : (
              <Link to={path} className="text-surface-400 hover:text-surface-600">
                {formatSegment(segment)}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
