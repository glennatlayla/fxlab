/**
 * Governance feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for approval requests, overrides, promotions,
 *   and related governance workflows. Mirrors the backend's Pydantic contracts
 *   in libs/contracts/governance.py.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of API responses.
 *   - TypeScript types inferred from Zod schemas.
 *   - Enum values for governance statuses, override types, target environments.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { ApprovalDetailSchema, type ApprovalDetail } from "@/types/governance";
 *   const result = ApprovalDetailSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Governance request status — shared by approvals, overrides, and promotions. */
export const GovernanceStatus = {
  PENDING: "pending",
  APPROVED: "approved",
  REJECTED: "rejected",
} as const;

export type GovernanceStatus = (typeof GovernanceStatus)[keyof typeof GovernanceStatus];

/** Override type — blocker waiver or grade override. */
export const OverrideType = {
  BLOCKER_WAIVER: "blocker_waiver",
  GRADE_OVERRIDE: "grade_override",
} as const;

export type OverrideType = (typeof OverrideType)[keyof typeof OverrideType];

/** Target deployment environment for promotions. */
export const TargetEnvironment = {
  PAPER: "paper",
  LIVE: "live",
} as const;

export type TargetEnvironment = (typeof TargetEnvironment)[keyof typeof TargetEnvironment];

// ---------------------------------------------------------------------------
// Approval schemas
// ---------------------------------------------------------------------------

/**
 * Schema for a single approval request detail, as returned by the API.
 *
 * Mirrors backend ApprovalRequest ORM model fields.
 */
export const ApprovalDetailSchema = z.object({
  id: z.string().min(1),
  candidate_id: z.string().min(1).optional(),
  entity_type: z.string().optional(),
  entity_id: z.string().optional(),
  requested_by: z.string().min(1),
  reviewer_id: z.string().nullable().optional(),
  status: z.enum(["pending", "approved", "rejected"]),
  decision_reason: z.string().nullable().optional(),
  decided_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string().optional(),
});

export type ApprovalDetail = z.infer<typeof ApprovalDetailSchema>;

/** Schema for a list of approval requests. */
export const ApprovalListSchema = z.array(ApprovalDetailSchema);

export type ApprovalList = z.infer<typeof ApprovalListSchema>;

/** Schema for the approve/reject response from the backend. */
export const ApprovalDecisionResponseSchema = z.object({
  approval_id: z.string().min(1),
  status: z.enum(["approved", "rejected"]),
  rationale: z.string().optional(),
});

export type ApprovalDecisionResponse = z.infer<typeof ApprovalDecisionResponseSchema>;

// ---------------------------------------------------------------------------
// Override schemas
// ---------------------------------------------------------------------------

/** Schema for override detail as returned by GET /overrides/{id}. */
export const OverrideDetailSchema = z.object({
  id: z.string().min(1),
  object_id: z.string().min(1),
  object_type: z.enum(["candidate", "deployment"]),
  override_type: z.enum(["blocker_waiver", "grade_override"]),
  original_state: z.record(z.string(), z.unknown()),
  new_state: z.record(z.string(), z.unknown()),
  evidence_link: z.string().url(),
  rationale: z.string().min(1),
  submitter_id: z.string().min(1),
  status: z.enum(["pending", "approved", "rejected"]),
  reviewed_by: z.string().nullable().optional(),
  reviewed_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  override_watermark: z.record(z.string(), z.unknown()).nullable().optional(),
});

export type OverrideDetail = z.infer<typeof OverrideDetailSchema>;

/** Schema for a list of overrides. */
export const OverrideListSchema = z.array(OverrideDetailSchema);

export type OverrideList = z.infer<typeof OverrideListSchema>;

/** Schema for override request creation response. */
export const OverrideCreateResponseSchema = z.object({
  override_id: z.string().min(1),
  status: z.enum(["pending"]),
});

export type OverrideCreateResponse = z.infer<typeof OverrideCreateResponseSchema>;

// ---------------------------------------------------------------------------
// Promotion schemas
// ---------------------------------------------------------------------------

/** Schema for promotion request response from POST /promotions/request. */
export const PromotionRequestResponseSchema = z.object({
  job_id: z.string().min(1),
  status: z.enum([
    "pending",
    "validating",
    "approved",
    "rejected",
    "deploying",
    "completed",
    "failed",
  ]),
});

export type PromotionRequestResponse = z.infer<typeof PromotionRequestResponseSchema>;

/** Schema for promotion history entry. */
export const PromotionHistoryEntrySchema = z.object({
  id: z.string().min(1),
  candidate_id: z.string().min(1),
  target_environment: z.enum(["paper", "live"]),
  submitted_by: z.string().min(1),
  status: z.enum([
    "pending",
    "validating",
    "approved",
    "rejected",
    "deploying",
    "completed",
    "failed",
  ]),
  reviewed_by: z.string().nullable().optional(),
  reviewed_at: z.string().nullable().optional(),
  decision_rationale: z.string().nullable().optional(),
  evidence_link: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  override_watermark: z.record(z.string(), z.unknown()).nullable().optional(),
});

export type PromotionHistoryEntry = z.infer<typeof PromotionHistoryEntrySchema>;

/** Schema for a list of promotion history entries. */
export const PromotionHistoryListSchema = z.array(PromotionHistoryEntrySchema);

export type PromotionHistoryList = z.infer<typeof PromotionHistoryListSchema>;

// ---------------------------------------------------------------------------
// Request payloads (used for form validation on the client)
// ---------------------------------------------------------------------------

/** Client-side validation for approval rejection form. */
export const ApprovalRejectFormSchema = z.object({
  rationale: z.string().min(10, "Rejection rationale must be at least 10 characters"),
});

export type ApprovalRejectForm = z.infer<typeof ApprovalRejectFormSchema>;

/** Client-side validation for override request form. */
export const OverrideRequestFormSchema = z.object({
  object_id: z.string().min(1, "Target object is required"),
  object_type: z.enum(["candidate", "deployment"]),
  override_type: z.enum(["blocker_waiver", "grade_override"]),
  original_state: z.record(z.string(), z.unknown()),
  new_state: z.record(z.string(), z.unknown()),
  evidence_link: z
    .string()
    .url("Paste a link to your Jira ticket, Confluence doc, or GitHub issue")
    .refine(
      (val) => {
        try {
          const parsed = new URL(val);
          return (
            (parsed.protocol === "http:" || parsed.protocol === "https:") &&
            parsed.pathname.replace(/\/+$/, "").length > 0
          );
        } catch {
          return false;
        }
      },
      {
        message:
          "Evidence link must be an HTTP/HTTPS URL pointing to a specific resource (not just the host)",
      },
    ),
  rationale: z
    .string()
    .min(20, "Override rationale must be at least 20 characters (SOC 2 requirement)"),
});

export type OverrideRequestForm = z.infer<typeof OverrideRequestFormSchema>;
