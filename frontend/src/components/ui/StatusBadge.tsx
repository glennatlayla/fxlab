/**
 * StatusBadge — colored pill for entity status values.
 *
 * Maps status strings to color variants. Unknown statuses render in gray.
 *
 * Example:
 *   <StatusBadge status="approved" />
 *   <StatusBadge status="pending" />
 */

import { clsx } from "clsx";

type StatusVariant = "success" | "warning" | "danger" | "info" | "neutral";

const STATUS_MAP: Record<string, StatusVariant> = {
  approved: "success",
  completed: "success",
  healthy: "success",
  active: "success",
  connected: "success",
  pending: "warning",
  in_progress: "warning",
  degraded: "warning",
  rejected: "danger",
  failed: "danger",
  unhealthy: "danger",
  disconnected: "danger",
  draft: "info",
  queued: "info",
};

const VARIANT_CLASSES: Record<StatusVariant, string> = {
  success: "bg-green-50 text-green-700 ring-green-600/20",
  warning: "bg-yellow-50 text-yellow-700 ring-yellow-600/20",
  danger: "bg-red-50 text-red-700 ring-red-600/20",
  info: "bg-blue-50 text-blue-700 ring-blue-600/20",
  neutral: "bg-surface-100 text-surface-600 ring-surface-500/20",
};

interface StatusBadgeProps {
  /** The status string to render. */
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const variant = STATUS_MAP[status.toLowerCase()] ?? "neutral";
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium ring-1 ring-inset",
        VARIANT_CLASSES[variant],
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
