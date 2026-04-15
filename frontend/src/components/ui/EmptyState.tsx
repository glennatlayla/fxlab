/**
 * EmptyState — placeholder for pages/sections with no data.
 *
 * Example:
 *   <EmptyState title="No runs yet" description="Start a backtest run..." />
 */

import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  /** Heading displayed in the empty state. */
  title: string;
  /** Explanatory text below the heading. */
  description?: string;
  /** Optional action button or link. */
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <Inbox className="h-12 w-12 text-surface-300" />
      <h3 className="text-lg font-medium text-surface-700">{title}</h3>
      {description && <p className="max-w-sm text-sm text-surface-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
