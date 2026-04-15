/**
 * Tests for governance Zod schemas.
 *
 * Validates schema acceptance/rejection for all governance types,
 * including edge cases for evidence_link SOC 2 validation.
 */

import { describe, it, expect } from "vitest";
import {
  ApprovalDetailSchema,
  ApprovalListSchema,
  ApprovalDecisionResponseSchema,
  ApprovalRejectFormSchema,
  OverrideDetailSchema,
  OverrideListSchema,
  OverrideCreateResponseSchema,
  OverrideRequestFormSchema,
  PromotionRequestResponseSchema,
  PromotionHistoryEntrySchema,
  PromotionHistoryListSchema,
} from "./governance";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeApproval(overrides?: Record<string, unknown>) {
  return {
    id: "01HAPPROVAL000000000001",
    requested_by: "01HUSER0000000000000001",
    status: "pending",
    created_at: "2026-04-06T12:00:00Z",
    ...overrides,
  };
}

function makeOverride(overrides?: Record<string, unknown>) {
  return {
    id: "01HOVERRIDE000000000001",
    object_id: "01HCANDIDATE0000000001",
    object_type: "candidate",
    override_type: "grade_override",
    original_state: { grade: "C" },
    new_state: { grade: "B" },
    evidence_link: "https://jira.example.com/browse/FX-123",
    rationale: "Extended backtest justifies grade uplift",
    submitter_id: "01HUSER0000000000000001",
    status: "pending",
    reviewed_by: null,
    reviewed_at: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
    override_watermark: null,
    ...overrides,
  };
}

function makePromotionHistory(overrides?: Record<string, unknown>) {
  return {
    id: "01HPROMO00000000000001",
    candidate_id: "01HCANDIDATE0000000001",
    target_environment: "paper",
    submitted_by: "01HUSER0000000000000001",
    status: "pending",
    reviewed_by: null,
    reviewed_at: null,
    decision_rationale: null,
    evidence_link: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
    override_watermark: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// ApprovalDetailSchema
// ---------------------------------------------------------------------------

describe("ApprovalDetailSchema", () => {
  it("accepts valid approval", () => {
    const result = ApprovalDetailSchema.safeParse(makeApproval());
    expect(result.success).toBe(true);
  });

  it("accepts approval with all optional fields", () => {
    const result = ApprovalDetailSchema.safeParse(
      makeApproval({
        candidate_id: "01HCANDIDATE0000000001",
        entity_type: "promotion",
        entity_id: "01HENTITY0000000000001",
        reviewer_id: "01HUSER0000000000000002",
        decision_reason: "Looks good, approved.",
        decided_at: "2026-04-06T14:00:00Z",
        updated_at: "2026-04-06T14:00:00Z",
      }),
    );
    expect(result.success).toBe(true);
  });

  it("rejects approval with empty id", () => {
    const result = ApprovalDetailSchema.safeParse(makeApproval({ id: "" }));
    expect(result.success).toBe(false);
  });

  it("rejects approval with invalid status", () => {
    const result = ApprovalDetailSchema.safeParse(makeApproval({ status: "unknown" }));
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// ApprovalListSchema
// ---------------------------------------------------------------------------

describe("ApprovalListSchema", () => {
  it("accepts empty array", () => {
    expect(ApprovalListSchema.safeParse([]).success).toBe(true);
  });

  it("accepts array of valid approvals", () => {
    const result = ApprovalListSchema.safeParse([
      makeApproval(),
      makeApproval({ id: "01HAPPROVAL000000000002", status: "approved" }),
    ]);
    expect(result.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ApprovalDecisionResponseSchema
// ---------------------------------------------------------------------------

describe("ApprovalDecisionResponseSchema", () => {
  it("accepts approved response", () => {
    const result = ApprovalDecisionResponseSchema.safeParse({
      approval_id: "01HAPPROVAL000000000001",
      status: "approved",
    });
    expect(result.success).toBe(true);
  });

  it("accepts rejected response with rationale", () => {
    const result = ApprovalDecisionResponseSchema.safeParse({
      approval_id: "01HAPPROVAL000000000001",
      status: "rejected",
      rationale: "Evidence link is stale",
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid status", () => {
    const result = ApprovalDecisionResponseSchema.safeParse({
      approval_id: "01HAPPROVAL000000000001",
      status: "pending",
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// ApprovalRejectFormSchema
// ---------------------------------------------------------------------------

describe("ApprovalRejectFormSchema", () => {
  it("accepts valid rationale", () => {
    expect(
      ApprovalRejectFormSchema.safeParse({
        rationale: "This does not meet the criteria set out in the spec.",
      }).success,
    ).toBe(true);
  });

  it("rejects rationale under 10 characters", () => {
    const result = ApprovalRejectFormSchema.safeParse({ rationale: "too short" });
    expect(result.success).toBe(false);
  });

  it("rejects empty rationale", () => {
    expect(ApprovalRejectFormSchema.safeParse({ rationale: "" }).success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// OverrideDetailSchema
// ---------------------------------------------------------------------------

describe("OverrideDetailSchema", () => {
  it("accepts valid override", () => {
    expect(OverrideDetailSchema.safeParse(makeOverride()).success).toBe(true);
  });

  it("accepts override with approved status and reviewer", () => {
    const result = OverrideDetailSchema.safeParse(
      makeOverride({
        status: "approved",
        reviewed_by: "01HUSER0000000000000002",
        reviewed_at: "2026-04-06T14:00:00Z",
      }),
    );
    expect(result.success).toBe(true);
  });

  it("rejects override with invalid object_type", () => {
    const result = OverrideDetailSchema.safeParse(makeOverride({ object_type: "strategy" }));
    expect(result.success).toBe(false);
  });

  it("rejects override with invalid evidence_link", () => {
    const result = OverrideDetailSchema.safeParse(makeOverride({ evidence_link: "not-a-url" }));
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// OverrideListSchema
// ---------------------------------------------------------------------------

describe("OverrideListSchema", () => {
  it("accepts empty array", () => {
    expect(OverrideListSchema.safeParse([]).success).toBe(true);
  });

  it("accepts array of valid overrides", () => {
    const result = OverrideListSchema.safeParse([
      makeOverride(),
      makeOverride({ id: "01HOVERRIDE000000000002", status: "approved" }),
    ]);
    expect(result.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// OverrideCreateResponseSchema
// ---------------------------------------------------------------------------

describe("OverrideCreateResponseSchema", () => {
  it("accepts valid response", () => {
    const result = OverrideCreateResponseSchema.safeParse({
      override_id: "01HOVERRIDE000000000001",
      status: "pending",
    });
    expect(result.success).toBe(true);
  });

  it("rejects non-pending status", () => {
    const result = OverrideCreateResponseSchema.safeParse({
      override_id: "01HOVERRIDE000000000001",
      status: "approved",
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// OverrideRequestFormSchema — evidence_link SOC 2 validation
// ---------------------------------------------------------------------------

describe("OverrideRequestFormSchema", () => {
  const validForm = {
    object_id: "01HCANDIDATE0000000001",
    object_type: "candidate" as const,
    override_type: "grade_override" as const,
    original_state: { grade: "C" },
    new_state: { grade: "B" },
    evidence_link: "https://jira.example.com/browse/FX-123",
    rationale: "Extended backtest over 3-year window justifies grade uplift.",
  };

  it("accepts valid override request form", () => {
    expect(OverrideRequestFormSchema.safeParse(validForm).success).toBe(true);
  });

  it("rejects empty evidence_link", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "",
    });
    expect(result.success).toBe(false);
  });

  it("rejects non-URL evidence_link", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "not-a-url",
    });
    expect(result.success).toBe(false);
  });

  it("rejects evidence_link with root-only path", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "https://jira.example.com/",
    });
    expect(result.success).toBe(false);
  });

  it("rejects evidence_link with bare domain (no trailing slash)", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "https://jira.example.com",
    });
    expect(result.success).toBe(false);
  });

  it("rejects javascript: protocol in evidence_link", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "javascript:alert(1)",
    });
    expect(result.success).toBe(false);
  });

  it("rejects ftp: protocol in evidence_link", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "ftp://evil.example.com/payload",
    });
    expect(result.success).toBe(false);
  });

  it("accepts http: evidence_link with path", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      evidence_link: "http://internal.jira/RISK-99",
    });
    expect(result.success).toBe(true);
  });

  it("rejects rationale under 20 characters", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      rationale: "too short for SOC2",
    });
    expect(result.success).toBe(false);
  });

  it("rejects invalid object_type", () => {
    const result = OverrideRequestFormSchema.safeParse({
      ...validForm,
      object_type: "strategy",
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PromotionRequestResponseSchema
// ---------------------------------------------------------------------------

describe("PromotionRequestResponseSchema", () => {
  it("accepts valid pending response", () => {
    const result = PromotionRequestResponseSchema.safeParse({
      job_id: "01HJOB000000000000001",
      status: "pending",
    });
    expect(result.success).toBe(true);
  });

  it("accepts all valid statuses", () => {
    for (const status of [
      "pending",
      "validating",
      "approved",
      "rejected",
      "deploying",
      "completed",
      "failed",
    ]) {
      const result = PromotionRequestResponseSchema.safeParse({
        job_id: "01HJOB000000000000001",
        status,
      });
      expect(result.success).toBe(true);
    }
  });

  it("rejects invalid status", () => {
    const result = PromotionRequestResponseSchema.safeParse({
      job_id: "01HJOB000000000000001",
      status: "unknown",
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PromotionHistoryEntrySchema
// ---------------------------------------------------------------------------

describe("PromotionHistoryEntrySchema", () => {
  it("accepts valid promotion history entry", () => {
    expect(PromotionHistoryEntrySchema.safeParse(makePromotionHistory()).success).toBe(true);
  });

  it("accepts entry with all optional fields populated", () => {
    const result = PromotionHistoryEntrySchema.safeParse(
      makePromotionHistory({
        reviewed_by: "01HUSER0000000000000002",
        reviewed_at: "2026-04-06T14:00:00Z",
        decision_rationale: "Approved after review.",
        evidence_link: "https://jira.example.com/FX-456",
        override_watermark: { override_id: "01HOVERRIDE" },
      }),
    );
    expect(result.success).toBe(true);
  });

  it("rejects entry with invalid target_environment", () => {
    const result = PromotionHistoryEntrySchema.safeParse(
      makePromotionHistory({ target_environment: "staging" }),
    );
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PromotionHistoryListSchema
// ---------------------------------------------------------------------------

describe("PromotionHistoryListSchema", () => {
  it("accepts empty list", () => {
    expect(PromotionHistoryListSchema.safeParse([]).success).toBe(true);
  });

  it("accepts list of entries", () => {
    const result = PromotionHistoryListSchema.safeParse([
      makePromotionHistory(),
      makePromotionHistory({
        id: "01HPROMO00000000000002",
        status: "approved",
      }),
    ]);
    expect(result.success).toBe(true);
  });
});
