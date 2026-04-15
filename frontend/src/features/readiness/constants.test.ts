/**
 * Tests for Readiness feature constants.
 *
 * Verifies grade color mapping, dimension config, and constant values.
 */

import { describe, it, expect } from "vitest";
import {
  GRADE_BADGE_CLASSES,
  GRADE_INTERPRETATION,
  GRADE_THRESHOLDS,
  DIMENSION_CONFIG,
  OVERRIDE_WATERMARK_CLASSES,
  BLOCKER_SEVERITY_CLASSES,
  READINESS_API_MAX_RETRIES,
  READINESS_API_RETRY_BASE_DELAY_MS,
  READINESS_API_JITTER_FACTOR,
  OP_FETCH_READINESS,
  OP_GENERATE_READINESS,
  OP_SUBMIT_PROMOTION,
  OP_RENDER_PAGE,
} from "./constants";

describe("Readiness constants", () => {
  it("GRADE_BADGE_CLASSES covers all five grades", () => {
    const grades = ["A", "B", "C", "D", "F"] as const;
    for (const g of grades) {
      expect(GRADE_BADGE_CLASSES[g]).toBeTruthy();
      expect(GRADE_BADGE_CLASSES[g]).toContain("bg-");
    }
  });

  it("GRADE_INTERPRETATION covers all five grades", () => {
    expect(GRADE_INTERPRETATION.A).toContain("confidence");
    expect(GRADE_INTERPRETATION.B).toContain("monitoring");
    expect(GRADE_INTERPRETATION.C).toContain("Address");
    expect(GRADE_INTERPRETATION.D).toContain("concerns");
    expect(GRADE_INTERPRETATION.F).toContain("Do not proceed");
  });

  it("GRADE_THRESHOLDS are in descending order", () => {
    expect(GRADE_THRESHOLDS.A).toBeGreaterThan(GRADE_THRESHOLDS.B);
    expect(GRADE_THRESHOLDS.B).toBeGreaterThan(GRADE_THRESHOLDS.C);
    expect(GRADE_THRESHOLDS.C).toBeGreaterThan(GRADE_THRESHOLDS.D);
    expect(GRADE_THRESHOLDS.D).toBeGreaterThan(GRADE_THRESHOLDS.F);
  });

  it("DIMENSION_CONFIG covers all six scoring dimensions", () => {
    const expected = [
      "oos_stability",
      "drawdown",
      "trade_count",
      "holdout_pass",
      "regime_consistency",
      "parameter_stability",
    ];
    for (const dim of expected) {
      expect(DIMENSION_CONFIG[dim]).toBeDefined();
      expect(DIMENSION_CONFIG[dim].label).toBeTruthy();
      expect(DIMENSION_CONFIG[dim].failDescription).toBeTruthy();
    }
  });

  it("OVERRIDE_WATERMARK_CLASSES contains amber styling", () => {
    expect(OVERRIDE_WATERMARK_CLASSES).toContain("amber");
  });

  it("BLOCKER_SEVERITY_CLASSES covers all severity levels", () => {
    expect(BLOCKER_SEVERITY_CLASSES.critical).toContain("red");
    expect(BLOCKER_SEVERITY_CLASSES.high).toContain("orange");
    expect(BLOCKER_SEVERITY_CLASSES.medium).toContain("yellow");
    expect(BLOCKER_SEVERITY_CLASSES.low).toContain("slate");
  });

  it("API retry values are sensible", () => {
    expect(READINESS_API_MAX_RETRIES).toBe(3);
    expect(READINESS_API_RETRY_BASE_DELAY_MS).toBe(1000);
    expect(READINESS_API_JITTER_FACTOR).toBeGreaterThan(0);
    expect(READINESS_API_JITTER_FACTOR).toBeLessThan(1);
  });

  it("logging operation names follow convention", () => {
    expect(OP_FETCH_READINESS).toBe("readiness.fetch_report");
    expect(OP_GENERATE_READINESS).toBe("readiness.generate_report");
    expect(OP_SUBMIT_PROMOTION).toBe("readiness.submit_promotion");
    expect(OP_RENDER_PAGE).toBe("readiness.render_page");
  });
});
