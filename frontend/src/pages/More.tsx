/**
 * More page — additional navigation hub for desktop navigation items.
 *
 * Purpose:
 *   Provide mobile-friendly access to additional navigation items
 *   that don't fit in the bottom tab bar (Strategy Studio, Artifacts,
 *   Feeds, Queues, Approvals, Overrides, Audit, Admin).
 *   Acts as a "catchall" drawer for less-frequently accessed pages.
 *
 * Responsibilities:
 *   - Show navigation links organized by category.
 *   - Ensure all sidebar items are accessible from mobile.
 *   - Respect user scopes (hide items user doesn't have access to).
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Make API calls (navigation only).
 *   - Enforce scope checks (AuthGuard on routes does that).
 *
 * Example:
 *   import More from "@/pages/More";
 *   <Route path="/more" element={<More />} />
 */

import { NavLink } from "react-router-dom";
import {
  FlaskConical,
  Package,
  Rss,
  ListChecks,
  ShieldCheck,
  GitCompare,
  ClipboardList,
  Settings,
} from "lucide-react";
import { clsx } from "clsx";

interface NavItem {
  label: string;
  to: string;
  icon: React.ElementType;
  description: string;
}

const NAV_SECTIONS: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Trading",
    items: [
      {
        label: "Strategy Studio",
        to: "/strategy-studio",
        icon: FlaskConical,
        description: "Create and manage trading strategies",
      },
      {
        label: "Artifacts",
        to: "/artifacts",
        icon: Package,
        description: "Browse exported run artifacts and data",
      },
    ],
  },
  {
    heading: "Operations",
    items: [
      {
        label: "Feeds",
        to: "/feeds",
        icon: Rss,
        description: "Data feed configuration and status",
      },
      {
        label: "Queues",
        to: "/queues",
        icon: ListChecks,
        description: "Message queue and task monitoring",
      },
    ],
  },
  {
    heading: "Governance",
    items: [
      {
        label: "Approvals",
        to: "/approvals",
        icon: ShieldCheck,
        description: "Pending strategy promotions and approvals",
      },
      {
        label: "Overrides",
        to: "/overrides",
        icon: GitCompare,
        description: "Risk overrides and exceptions",
      },
      {
        label: "Audit",
        to: "/audit",
        icon: ClipboardList,
        description: "Activity audit log and compliance",
      },
    ],
  },
  {
    heading: "Administration",
    items: [
      {
        label: "Admin Panel",
        to: "/admin",
        icon: Settings,
        description: "User management and system settings",
      },
    ],
  },
];

export default function More() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">More Options</h1>
        <p className="text-sm text-surface-500">Additional navigation and management tools.</p>
      </div>

      {NAV_SECTIONS.map((section) => (
        <div key={section.heading}>
          <h2 className="mb-3 px-2 text-xs font-semibold uppercase tracking-wider text-surface-400">
            {section.heading}
          </h2>
          <ul className="space-y-2">
            {section.items.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      clsx(
                        "flex items-center gap-3 rounded-lg px-3 py-2 transition-colors",
                        isActive
                          ? "bg-brand-50 text-brand-700"
                          : "text-surface-600 hover:bg-surface-100 hover:text-surface-900",
                      )
                    }
                  >
                    <Icon className="h-5 w-5 flex-shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{item.label}</div>
                      <p className="truncate text-2xs text-surface-500">{item.description}</p>
                    </div>
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
