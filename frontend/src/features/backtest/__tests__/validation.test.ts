/**
 * Unit tests for backtest validation schema.
 *
 * Covers all validation rules, edge cases, and cross-field constraints.
 */

import { describe, it, expect } from "vitest";
import { backtestFormSchema, validateBacktestForm } from "../validation";
import type { BacktestFormValues } from "../types";

describe("backtestFormSchema", () => {
  const validFormValues: BacktestFormValues = {
    strategy_build_id: "strat-abc123",
    symbols: ["AAPL", "MSFT"],
    start_date: "2024-01-01",
    end_date: "2024-12-31",
    interval: "1d",
    initial_equity: 10_000,
  };

  describe("valid forms", () => {
    it("accepts a valid research backtest form", () => {
      const result = backtestFormSchema.safeParse(validFormValues);
      expect(result.success).toBe(true);
    });

    it("accepts optional advanced settings", () => {
      const withAdvanced = {
        ...validFormValues,
        commission_rate: 0.001,
        slippage_bps: 5,
      };
      const result = backtestFormSchema.safeParse(withAdvanced);
      expect(result.success).toBe(true);
    });

    it("accepts minimum equity of $100", () => {
      const form = { ...validFormValues, initial_equity: 100 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("accepts maximum equity of $10M", () => {
      const form = { ...validFormValues, initial_equity: 10_000_000 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("accepts zero commission rate", () => {
      const form = { ...validFormValues, commission_rate: 0 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("accepts maximum commission rate of 10%", () => {
      const form = { ...validFormValues, commission_rate: 0.1 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("accepts zero slippage", () => {
      const form = { ...validFormValues, slippage_bps: 0 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("accepts maximum slippage of 100 bps", () => {
      const form = { ...validFormValues, slippage_bps: 100 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("normalizes symbol case to uppercase", () => {
      const form = { ...validFormValues, symbols: ["aapl", "msft"] };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.symbols).toEqual(["AAPL", "MSFT"]);
      }
    });

    it("trims symbol whitespace", () => {
      const form = { ...validFormValues, symbols: [" AAPL ", " MSFT "] };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.symbols).toEqual(["AAPL", "MSFT"]);
      }
    });
  });

  describe("strategy_build_id validation", () => {
    it("rejects empty strategy_build_id", () => {
      const form = { ...validFormValues, strategy_build_id: "" };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.strategy_build_id).toBeDefined();
      }
    });

    it("rejects missing strategy_build_id", () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars -- destructure-to-omit
      const { strategy_build_id, ...form } = validFormValues;
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
    });
  });

  describe("symbols validation", () => {
    it("rejects empty symbols array", () => {
      const form = { ...validFormValues, symbols: [] };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.symbols).toBeDefined();
      }
    });

    it("rejects missing symbols", () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars -- destructure-to-omit
      const { symbols, ...form } = validFormValues;
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
    });

    it("accepts single symbol", () => {
      const form = { ...validFormValues, symbols: ["AAPL"] };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });

    it("accepts multiple symbols", () => {
      const form = {
        ...validFormValues,
        symbols: ["AAPL", "MSFT", "GOOGL", "AMZN"],
      };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });
  });

  describe("date validation", () => {
    it("rejects invalid start_date format", () => {
      const form = { ...validFormValues, start_date: "01/01/2024" };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.start_date).toBeDefined();
      }
    });

    it("rejects invalid end_date format", () => {
      const form = { ...validFormValues, end_date: "2024/12/31" };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.end_date).toBeDefined();
      }
    });

    it("rejects end_date before start_date", () => {
      const form = {
        ...validFormValues,
        start_date: "2024-12-31",
        end_date: "2024-01-01",
      };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.end_date).toBeDefined();
      }
    });

    it("rejects end_date equal to start_date", () => {
      const form = {
        ...validFormValues,
        start_date: "2024-01-01",
        end_date: "2024-01-01",
      };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
    });

    it("accepts end_date far in future", () => {
      const form = {
        ...validFormValues,
        start_date: "2024-01-01",
        end_date: "2100-12-31",
      };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });
  });

  describe("interval validation", () => {
    it("rejects invalid interval", () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- intentionally-invalid-interval-for-test
      const form = { ...validFormValues, interval: "2h" as any };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.interval).toBeDefined();
      }
    });

    it("accepts all valid intervals", () => {
      const intervals = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
      for (const interval of intervals) {
        const form = { ...validFormValues, interval };
        const result = backtestFormSchema.safeParse(form);
        expect(result.success).toBe(true);
      }
    });
  });

  describe("initial_equity validation", () => {
    it("rejects equity below minimum ($100)", () => {
      const form = { ...validFormValues, initial_equity: 99 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.initial_equity).toBeDefined();
      }
    });

    it("rejects equity above maximum ($10M)", () => {
      const form = { ...validFormValues, initial_equity: 10_000_001 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.initial_equity).toBeDefined();
      }
    });

    it("rejects non-integer equity", () => {
      const form = { ...validFormValues, initial_equity: 10_000.5 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.initial_equity).toBeDefined();
      }
    });
  });

  describe("commission_rate validation", () => {
    it("rejects negative commission rate", () => {
      const form = { ...validFormValues, commission_rate: -0.001 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.commission_rate).toBeDefined();
      }
    });

    it("rejects commission rate above 10%", () => {
      const form = { ...validFormValues, commission_rate: 0.11 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.commission_rate).toBeDefined();
      }
    });

    it("treats undefined commission_rate as optional", () => {
      const form = { ...validFormValues };
      delete form.commission_rate;
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });
  });

  describe("slippage_bps validation", () => {
    it("rejects negative slippage", () => {
      const form = { ...validFormValues, slippage_bps: -1 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.slippage_bps).toBeDefined();
      }
    });

    it("rejects slippage above 100 bps", () => {
      const form = { ...validFormValues, slippage_bps: 101 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.slippage_bps).toBeDefined();
      }
    });

    it("rejects non-integer slippage", () => {
      const form = { ...validFormValues, slippage_bps: 5.5 };
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.slippage_bps).toBeDefined();
      }
    });

    it("treats undefined slippage_bps as optional", () => {
      const form = { ...validFormValues };
      delete form.slippage_bps;
      const result = backtestFormSchema.safeParse(form);
      expect(result.success).toBe(true);
    });
  });
});

describe("validateBacktestForm helper", () => {
  const validForm: BacktestFormValues = {
    strategy_build_id: "strat-abc123",
    symbols: ["AAPL"],
    start_date: "2024-01-01",
    end_date: "2024-12-31",
    interval: "1d",
    initial_equity: 10_000,
  };

  it("returns success: true and data on valid form", () => {
    const result = validateBacktestForm(validForm);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toEqual(validForm);
    }
  });

  it("returns success: false and errors on invalid form", () => {
    const form = { ...validForm, initial_equity: 50 };
    const result = validateBacktestForm(form);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.errors).toBeDefined();
      expect(result.errors.initial_equity).toBeDefined();
    }
  });

  it("provides flattened errors by field", () => {
    const form = {
      strategy_build_id: "",
      symbols: [],
      start_date: "invalid",
      end_date: "2024-01-01",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- intentionally-invalid-interval-for-test
      interval: "2h" as any,
      initial_equity: -100,
    };
    const result = validateBacktestForm(form);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(Object.keys(result.errors).length).toBeGreaterThan(0);
    }
  });
});
