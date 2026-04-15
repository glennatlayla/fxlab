/**
 * Tests for Zod runtime validation schemas for run domain types.
 *
 * Verifies that schemas correctly accept valid data and reject malformed
 * data for all run-related API response shapes.
 */

import { describe, it, expect } from "vitest";
import {
  RunTypeSchema,
  RunStatusSchema,
  TrialStatusSchema,
  BlockerDetailSchema,
  PreflightResultSchema,
  OverrideWatermarkSchema,
  TrialRecordSchema,
  RunRecordSchema,
  TrialListResponseSchema,
} from "./run.schemas";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

function makeValidRunRecord() {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: "research",
    status: "running",
    config: { instrument: "EURUSD", timeframe: "1h" },
    result_uri: null,
    created_by: "user-ulid-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:05:00Z",
    started_at: "2026-04-04T10:01:00Z",
    completed_at: null,
  };
}

function makeValidTrialRecord() {
  return {
    id: "01HZ0000000000000000000010",
    run_id: "01HZ0000000000000000000001",
    trial_index: 0,
    status: "completed",
    parameters: { lookback: 20, threshold: 0.5 },
    seed: 42,
    metrics: { sharpe: 1.5, max_drawdown: -0.08 },
    created_at: "2026-04-04T10:02:00Z",
    updated_at: "2026-04-04T10:03:00Z",
  };
}

function makeValidBlockerDetail() {
  return {
    code: "PREFLIGHT_FAILED",
    message: "Pre-run validation did not pass.",
    blocker_owner: "data-team@fxlab.io",
    next_step: "view_preflight",
    metadata: { check_id: "chk-001" },
  };
}

function makeValidOverrideWatermark() {
  return {
    override_id: "01HZ0000000000000000000099",
    approved_by: "admin@fxlab.io",
    approved_at: "2026-04-03T12:00:00Z",
    reason: "Emergency deployment required",
    revoked: false,
    revoked_at: null,
  };
}

// ---------------------------------------------------------------------------
// Enum schemas
// ---------------------------------------------------------------------------

describe("RunTypeSchema", () => {
  it("accepts 'research'", () => {
    expect(RunTypeSchema.parse("research")).toBe("research");
  });

  it("accepts 'optimization'", () => {
    expect(RunTypeSchema.parse("optimization")).toBe("optimization");
  });

  it("rejects unknown run type", () => {
    expect(() => RunTypeSchema.parse("backtest")).toThrow();
  });
});

describe("RunStatusSchema", () => {
  const validStatuses = ["pending", "running", "complete", "failed", "cancelled"];

  it.each(validStatuses)("accepts '%s'", (status) => {
    expect(RunStatusSchema.parse(status)).toBe(status);
  });

  it("rejects unknown status", () => {
    expect(() => RunStatusSchema.parse("paused")).toThrow();
  });
});

describe("TrialStatusSchema", () => {
  const validStatuses = ["pending", "running", "completed", "failed"];

  it.each(validStatuses)("accepts '%s'", (status) => {
    expect(TrialStatusSchema.parse(status)).toBe(status);
  });

  it("rejects unknown status", () => {
    expect(() => TrialStatusSchema.parse("cancelled")).toThrow();
  });
});

// ---------------------------------------------------------------------------
// BlockerDetailSchema
// ---------------------------------------------------------------------------

describe("BlockerDetailSchema", () => {
  it("accepts a valid blocker detail", () => {
    const blocker = makeValidBlockerDetail();
    const result = BlockerDetailSchema.parse(blocker);
    expect(result.code).toBe("PREFLIGHT_FAILED");
    expect(result.blocker_owner).toBe("data-team@fxlab.io");
  });

  it("rejects missing code field", () => {
    const { code: _code, ...incomplete } = makeValidBlockerDetail();
    expect(() => BlockerDetailSchema.parse(incomplete)).toThrow();
  });

  it("rejects missing message field", () => {
    const { message: _msg, ...incomplete } = makeValidBlockerDetail();
    expect(() => BlockerDetailSchema.parse(incomplete)).toThrow();
  });

  it("rejects missing blocker_owner field", () => {
    const { blocker_owner: _owner, ...incomplete } = makeValidBlockerDetail();
    expect(() => BlockerDetailSchema.parse(incomplete)).toThrow();
  });

  it("accepts empty metadata object", () => {
    const blocker = { ...makeValidBlockerDetail(), metadata: {} };
    expect(() => BlockerDetailSchema.parse(blocker)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// PreflightResultSchema
// ---------------------------------------------------------------------------

describe("PreflightResultSchema", () => {
  it("accepts a passing preflight result", () => {
    const result = PreflightResultSchema.parse({
      passed: true,
      blockers: [],
      checked_at: "2026-04-04T10:00:00Z",
    });
    expect(result.passed).toBe(true);
    expect(result.blockers).toHaveLength(0);
  });

  it("accepts a failing preflight result with blockers", () => {
    const result = PreflightResultSchema.parse({
      passed: false,
      blockers: [makeValidBlockerDetail()],
      checked_at: "2026-04-04T10:00:00Z",
    });
    expect(result.passed).toBe(false);
    expect(result.blockers).toHaveLength(1);
  });

  it("rejects missing passed field", () => {
    expect(() =>
      PreflightResultSchema.parse({
        blockers: [],
        checked_at: "2026-04-04T10:00:00Z",
      }),
    ).toThrow();
  });

  it("rejects non-boolean passed field", () => {
    expect(() =>
      PreflightResultSchema.parse({
        passed: "yes",
        blockers: [],
        checked_at: "2026-04-04T10:00:00Z",
      }),
    ).toThrow();
  });
});

// ---------------------------------------------------------------------------
// OverrideWatermarkSchema
// ---------------------------------------------------------------------------

describe("OverrideWatermarkSchema", () => {
  it("accepts a valid active override watermark", () => {
    const wm = makeValidOverrideWatermark();
    const result = OverrideWatermarkSchema.parse(wm);
    expect(result.override_id).toBe("01HZ0000000000000000000099");
    expect(result.revoked).toBe(false);
  });

  it("accepts a revoked override watermark", () => {
    const wm = {
      ...makeValidOverrideWatermark(),
      revoked: true,
      revoked_at: "2026-04-04T15:00:00Z",
    };
    const result = OverrideWatermarkSchema.parse(wm);
    expect(result.revoked).toBe(true);
    expect(result.revoked_at).toBe("2026-04-04T15:00:00Z");
  });

  it("accepts watermark without revoked_at (optional field)", () => {
    const { revoked_at: _ra, ...wm } = makeValidOverrideWatermark();
    expect(() => OverrideWatermarkSchema.parse(wm)).not.toThrow();
  });

  it("rejects missing approved_by field", () => {
    const { approved_by: _ab, ...incomplete } = makeValidOverrideWatermark();
    expect(() => OverrideWatermarkSchema.parse(incomplete)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// TrialRecordSchema
// ---------------------------------------------------------------------------

describe("TrialRecordSchema", () => {
  it("accepts a valid trial record", () => {
    const trial = makeValidTrialRecord();
    const result = TrialRecordSchema.parse(trial);
    expect(result.trial_index).toBe(0);
    expect(result.metrics?.sharpe).toBe(1.5);
  });

  it("accepts trial with null metrics", () => {
    const trial = { ...makeValidTrialRecord(), metrics: null };
    const result = TrialRecordSchema.parse(trial);
    expect(result.metrics).toBeNull();
  });

  it("accepts trial with fold_metrics", () => {
    const trial = {
      ...makeValidTrialRecord(),
      fold_metrics: {
        fold_0: { sharpe: 1.2, max_drawdown: -0.05 },
        fold_1: { sharpe: 1.8, max_drawdown: -0.12 },
      },
    };
    const result = TrialRecordSchema.parse(trial);
    expect(result.fold_metrics?.fold_0.sharpe).toBe(1.2);
  });

  it("accepts trial with objective_value", () => {
    const trial = { ...makeValidTrialRecord(), objective_value: 1.5 };
    const result = TrialRecordSchema.parse(trial);
    expect(result.objective_value).toBe(1.5);
  });

  it("accepts trial with null objective_value", () => {
    const trial = { ...makeValidTrialRecord(), objective_value: null };
    const result = TrialRecordSchema.parse(trial);
    expect(result.objective_value).toBeNull();
  });

  it("rejects negative trial_index", () => {
    const trial = { ...makeValidTrialRecord(), trial_index: -1 };
    expect(() => TrialRecordSchema.parse(trial)).toThrow();
  });

  it("rejects non-integer trial_index", () => {
    const trial = { ...makeValidTrialRecord(), trial_index: 1.5 };
    expect(() => TrialRecordSchema.parse(trial)).toThrow();
  });

  it("rejects invalid trial status", () => {
    const trial = { ...makeValidTrialRecord(), status: "cancelled" };
    expect(() => TrialRecordSchema.parse(trial)).toThrow();
  });

  it("rejects missing run_id", () => {
    const { run_id: _rid, ...incomplete } = makeValidTrialRecord();
    expect(() => TrialRecordSchema.parse(incomplete)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// RunRecordSchema
// ---------------------------------------------------------------------------

describe("RunRecordSchema", () => {
  it("accepts a valid minimal run record", () => {
    const run = makeValidRunRecord();
    const result = RunRecordSchema.parse(run);
    expect(result.id).toBe("01HZ0000000000000000000001");
    expect(result.run_type).toBe("research");
    expect(result.status).toBe("running");
  });

  it("accepts a complete run with all optional fields", () => {
    const run = {
      ...makeValidRunRecord(),
      status: "complete",
      result_uri: "s3://bucket/results/run-001.parquet",
      completed_at: "2026-04-04T11:00:00Z",
      trial_count: 100,
      completed_trials: 100,
      current_trial_params: null,
      error_message: null,
      cancellation_reason: null,
      override_watermarks: [makeValidOverrideWatermark()],
      preflight_results: [
        {
          passed: true,
          blockers: [],
          checked_at: "2026-04-04T09:59:00Z",
        },
      ],
    };
    const result = RunRecordSchema.parse(run);
    expect(result.trial_count).toBe(100);
    expect(result.override_watermarks).toHaveLength(1);
    expect(result.preflight_results).toHaveLength(1);
  });

  it("accepts a failed run with error message", () => {
    const run = {
      ...makeValidRunRecord(),
      status: "failed",
      error_message: "Out of memory during trial 42",
    };
    const result = RunRecordSchema.parse(run);
    expect(result.error_message).toBe("Out of memory during trial 42");
  });

  it("accepts a cancelled run with reason", () => {
    const run = {
      ...makeValidRunRecord(),
      status: "cancelled",
      cancellation_reason: "User requested cancellation",
    };
    const result = RunRecordSchema.parse(run);
    expect(result.cancellation_reason).toBe("User requested cancellation");
  });

  it("accepts optimization run type", () => {
    const run = { ...makeValidRunRecord(), run_type: "optimization" };
    const result = RunRecordSchema.parse(run);
    expect(result.run_type).toBe("optimization");
  });

  it("rejects unknown run type", () => {
    const run = { ...makeValidRunRecord(), run_type: "backtest" };
    expect(() => RunRecordSchema.parse(run)).toThrow();
  });

  it("rejects unknown status", () => {
    const run = { ...makeValidRunRecord(), status: "paused" };
    expect(() => RunRecordSchema.parse(run)).toThrow();
  });

  it("rejects missing id", () => {
    const { id: _id, ...incomplete } = makeValidRunRecord();
    expect(() => RunRecordSchema.parse(incomplete)).toThrow();
  });

  it("rejects missing strategy_build_id", () => {
    const { strategy_build_id: _sbid, ...incomplete } = makeValidRunRecord();
    expect(() => RunRecordSchema.parse(incomplete)).toThrow();
  });

  it("rejects negative trial_count", () => {
    const run = { ...makeValidRunRecord(), trial_count: -1 };
    expect(() => RunRecordSchema.parse(run)).toThrow();
  });

  it("rejects negative completed_trials", () => {
    const run = { ...makeValidRunRecord(), completed_trials: -5 };
    expect(() => RunRecordSchema.parse(run)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// TrialListResponseSchema
// ---------------------------------------------------------------------------

describe("TrialListResponseSchema", () => {
  it("accepts a valid trial list response", () => {
    const response = {
      trials: [makeValidTrialRecord()],
      total: 100,
      offset: 0,
      limit: 50,
    };
    const result = TrialListResponseSchema.parse(response);
    expect(result.trials).toHaveLength(1);
    expect(result.total).toBe(100);
  });

  it("accepts an empty trial list", () => {
    const response = {
      trials: [],
      total: 0,
      offset: 0,
      limit: 50,
    };
    const result = TrialListResponseSchema.parse(response);
    expect(result.trials).toHaveLength(0);
  });

  it("rejects missing total field", () => {
    expect(() =>
      TrialListResponseSchema.parse({
        trials: [],
        offset: 0,
        limit: 50,
      }),
    ).toThrow();
  });

  it("rejects zero limit", () => {
    expect(() =>
      TrialListResponseSchema.parse({
        trials: [],
        total: 0,
        offset: 0,
        limit: 0,
      }),
    ).toThrow();
  });

  it("rejects negative offset", () => {
    expect(() =>
      TrialListResponseSchema.parse({
        trials: [],
        total: 0,
        offset: -1,
        limit: 50,
      }),
    ).toThrow();
  });
});
