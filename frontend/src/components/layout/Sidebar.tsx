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
  Play,
  Rss,
  ShieldCheck,
  GitCompare,
  ClipboardList,
  ListChecks,
  Package,
} from "lucide-react";
import { clsx } from "clsx";

interface NavItem {
  label: string;
  to: string;
  icon: React.ElementType;
}

const NAV_SECTIONS: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Overview",
    items: [{ label: "Dashboard", to: "/", icon: LayoutDashboard }],
  },
  {
    heading: "Trading",
    items: [
      { label: "Strategy Studio", to: "/strategy-studio", icon: FlaskConical },
      { label: "Runs", to: "/runs", icon: Play },
      { label: "Artifacts", to: "/artifacts", icon: Package },
    ],
  },
  {
    heading: "Operations",
    items: [
      { label: "Feeds", to: "/feeds", icon: Rss },
      { label: "Queues", to: "/queues", icon: ListChecks },
    ],
  },
  {
    heading: "Governance",
    items: [
      { label: "Approvals", to: "/approvals", icon: ShieldCheck },
      { label: "Overrides", to: "/overrides", icon: GitCompare },
      { label: "Audit", to: "/audit", icon: ClipboardList },
    ],
  },
];

export function Sidebar() {
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
        {NAV_SECTIONS.map((section) => (
          <div key={section.heading}>
            <h3 className="mb-1 px-2 text-2xs font-semibold uppercase tracking-wider text-surface-400">
              {section.heading}
            </h3>
            <ul className="space-y-0.5">
              {section.items.map((item) => (
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
        ))}
      </nav>
    </aside>
  );
}
