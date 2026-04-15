/**
 * Shared API response type definitions.
 *
 * Purpose:
 *   Define typed shapes for all API responses consumed by TanStack Query
 *   hooks. Each type mirrors the backend's Pydantic response model.
 */

/** Standard error response from the API. */
export interface ApiError {
  detail: string;
  status_code?: number;
}

/** Health check response from GET /health. */
export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  database: "connected" | "disconnected";
  redis?: "connected" | "disconnected" | "not_configured";
}

/** Feed list item. */
export interface Feed {
  id: string;
  name: string;
  feed_type: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Override request. */
export interface Override {
  id: string;
  object_id: string;
  object_type: string;
  override_type: string;
  submitter_id: string;
  status: "pending" | "approved" | "rejected";
  rationale: string;
  evidence_link: string;
  created_at: string;
}

/** Approval request. */
export interface ApprovalRequest {
  id: string;
  entity_type: string;
  entity_id: string;
  requested_by: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
}

/** Draft autosave entry. */
export interface DraftAutosave {
  autosave_id: string;
  user_id: string;
  draft_payload: Record<string, unknown>;
  form_step: string;
  client_ts: string;
  session_id: string;
  created_at: string;
}

/** Audit event record. */
export interface AuditEvent {
  id: string;
  event_type: string;
  actor_id: string;
  target_type: string;
  target_id: string;
  detail: Record<string, unknown>;
  created_at: string;
}

/** Queue snapshot. */
export interface QueueSnapshot {
  name: string;
  pending: number;
  active: number;
  completed: number;
  failed: number;
}
