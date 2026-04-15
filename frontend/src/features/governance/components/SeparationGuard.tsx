/**
 * SeparationGuard — blocks action controls when the current user is the submitter.
 *
 * Purpose:
 *   Enforce separation of duties (SoD) in the UI by rendering a named
 *   status block that prevents submitters from interacting with approve/reject
 *   controls on their own requests. Per spec M29 AC-2.
 *
 * Responsibilities:
 *   - Compare current user ID against submitter ID.
 *   - When they match: render a read-only SoD violation notice and hide children.
 *   - When they differ: render children (the action controls).
 *
 * Does NOT:
 *   - Execute approval/rejection (parent handles that).
 *   - Fetch user data (parent provides currentUserId).
 *
 * Dependencies:
 *   - None (pure presentational component).
 *
 * Example:
 *   <SeparationGuard currentUserId={user.id} submitterId={request.requested_by}>
 *     <ApproveButton /> <RejectButton />
 *   </SeparationGuard>
 */

import { memo } from "react";
import type { ReactNode } from "react";

export interface SeparationGuardProps {
  /** ULID of the currently authenticated user. */
  currentUserId: string;
  /** ULID of the user who submitted the request. */
  submitterId: string;
  /** Action controls to render when SoD is satisfied. */
  children: ReactNode;
}

/**
 * Render action controls only when the current user is not the submitter.
 *
 * When the current user IS the submitter, a read-only notice is shown
 * explaining that separation of duties prevents self-review.
 *
 * Args:
 *   currentUserId: Authenticated user's ULID.
 *   submitterId: The request submitter's ULID.
 *   children: Controls to render when SoD is satisfied.
 *
 * Returns:
 *   Either the children or a SoD violation notice.
 */
export const SeparationGuard = memo(function SeparationGuard({
  currentUserId,
  submitterId,
  children,
}: SeparationGuardProps) {
  const isSameUser = currentUserId === submitterId;

  if (isSameUser) {
    return (
      <div
        data-testid="separation-guard-block"
        role="status"
        className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        <p className="font-medium">Separation of Duties</p>
        <p className="mt-1">
          You cannot review your own request. Another authorized user must approve or reject this
          item.
        </p>
      </div>
    );
  }

  return <>{children}</>;
});
