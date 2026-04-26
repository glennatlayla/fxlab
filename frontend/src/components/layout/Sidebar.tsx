/**
 * Sidebar navigation component.
 *
 * Purpose:
 *   Render the application's main navigation sidebar with categorized
 *   links to all M25–M31 page routes.
 *
 * Responsibilities:
 *   - Show navigation items grouped by category (Trading, Operations, Governance).
 *   - Highlight the currently active route.
 *   - Show/hide items based on user scopes (UI hint only — backend enforces).
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Make API calls.
 */

import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FlaskConical,
  FolderKanban,
  Play,
  Rss,
  ShieldCheck,
  GitCompare,
  ClipboardList,
  ListChecks,
  Package,
} from "lucide-react";
import { clsx } from "clsx";
import { useAuth } from "@/auth/useAuth";

interface NavItem {
  label: string;
  to: string;
  icon: React.ElementType;
  /**
   * Optional RBAC scope. When set, the link is hidden unless the
   * authenticated user holds the scope (matches the route-level
   * AuthGuard so the sidebar never shows a link the user would
   * immediately get a 403 from). Items without ``requiredScope`` are
   * always shown to authenticated users.
   */
  requiredScope?: string;
}

const NAV_SECTIONS: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Overview",
    items: [{ label: "Dashboard", to: "/", icon: LayoutDashboard }],
  },
  {
    heading: "Trading",
    items: [
      // Catalogue browse page (M2.D5) — listed before Strategy Studio so
      // operators discover existing strategies before importing more.
      {
        label: "Strategies",
        to: "/strategies",
        icon: FolderKanban,
        requiredScope: "strategies:write",
      },
      {
        label: "Strategy Studio",
        to: "/strategy-studio",
        icon: FlaskConical,
        requiredScope: "strategies:write",
      },
      { label: "Runs", to: "/runs", icon: Play, requiredScope: "runs:write" },
      { label: "Artifacts", to: "/artifacts", icon: Package, requiredScope: "exports:read" },
    ],
  },
  {
    heading: "Operations",
    items: [
      { label: "Feeds", to: "/feeds", icon: Rss, requiredScope: "feeds:read" },
      { label: "Queues", to: "/queues", icon: ListChecks, requiredScope: "feeds:read" },
    ],
  },
  {
    heading: "Governance",
    items: [
      {
        label: "Approvals",
        to: "/approvals",
        icon: ShieldCheck,
        requiredScope: "approvals:write",
      },
      {
        label: "Overrides",
        to: "/overrides",
        icon: GitCompare,
        requiredScope: "overrides:approve",
      },
      { label: "Audit", to: "/audit", icon: ClipboardList, requiredScope: "audit:read" },
    ],
  },
];

export function Sidebar() {
  // Hide nav links the user cannot access. Pulling hasScope from the
  // auth context lets us mirror the AuthGuard's logic so the sidebar
  // never renders a link to a route the user would immediately get a
  // 403 from (matches the M2.D5 acceptance: "the new sidebar link only
  // renders if the user has the strategies:write scope").
  const { hasScope } = useAuth();

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-sidebar flex-col border-r border-surface-200 bg-white lg:flex">
      {/* Brand */}
      <div className="flex h-topbar items-center border-b border-surface-200 px-4">
        <span className="text-lg font-bold text-brand-600">FXLab</span>
        <span className="ml-2 rounded bg-brand-100 px-1.5 py-0.5 text-2xs font-medium text-brand-700">
          Phase 3
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map((section) => {
          const visibleItems = section.items.filter(
            (item) => !item.requiredScope || hasScope(item.requiredScope),
          );
          if (visibleItems.length === 0) return null;
          return (
            <div key={section.heading}>
              <h3 className="mb-1 px-2 text-2xs font-semibold uppercase tracking-wider text-surface-400">
                {section.heading}
              </h3>
              <ul className="space-y-0.5">
                {visibleItems.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === "/"}
                      className={({ isActive }) =>
                        clsx(
                          "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                          isActive
                            ? "bg-brand-50 font-medium text-brand-700"
                            : "text-surface-600 hover:bg-surface-100 hover:text-surface-900",
                        )
                      }
                    >
                      <item.icon className="h-4 w-4 flex-shrink-0" />
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
