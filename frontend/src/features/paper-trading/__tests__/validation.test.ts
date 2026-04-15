/**
 * Unit tests for paper trading validation schemas.
 *
 * Purpose:
 *   Verify that Zod schemas enforce all domain constraints.
 *
 * Coverage:
 *   - Happy path: valid configuration passes.
 *   - Boundary values: min/max equity, leverage.
 *   - Error cases: missing fields, invalid ranges, empty arrays.
 *
 * Example:
 *   test_paperTradingConfigSchema_valid_config_parses
 *   test_paperTradingConfigSchema_equity_below_minimum_fails
 */

import { describe, it, expect } from "vitest";
import {
  paperTradingConfigSchema,
  type PaperTradingConfigInput,
} from "../validation";

describe("paperTradingConfigSchema", () => {
  /**
   * Test: valid configuration passes schema validation.
   */
  it("should parse valid config", () => {
    const validConfig: PaperTradingConfigInput = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL", "MSFT"],
    };

    const result = paperTradingConfigSchema.safeParse(validConfig);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toEqual(validConfig);
    }
  });

  /**
   * Test: equity below minimum fails.
   */
  it("should reject equity below $1,000", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 999,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.initial_equity).toBeDefined();
    }
  });

  /**
   * Test: equity above maximum fails.
   */
  it("should reject equity above $1,000,000", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 1000001,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.initial_equity).toBeDefined();
    }
  });

  /**
   * Test: equity at minimum boundary passes.
   */
  it("should accept equity at minimum boundary ($1,000)", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 1000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  /**
   * Test: leverage below minimum fails.
   */
  it("should reject leverage below 1x", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 0.5,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.max_leverage).toBeDefined();
    }
  });

  /**
   * Test: leverage above maximum fails.
   */
  it("should reject leverage above 10x", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 10.1,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.max_leverage).toBeDefined();
    }
  });

  /**
   * Test: leverage at maximum boundary passes.
   */
  it("should accept leverage at maximum boundary (10x)", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 10,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  /**
   * Test: missing deployment_id fails.
   */
  it("should reject missing deployment_id", () => {
    const config = {
      deployment_id: "",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.deployment_id).toBeDefined();
    }
  });

  /**
   * Test: empty symbols array fails.
   */
  it("should reject empty symbols array", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: [],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.symbols).toBeDefined();
    }
  });

  /**
   * Test: non-positive max_position_size fails.
   */
  it("should reject zero or negative max_position_size", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 0,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(
        result.error.flatten().fieldErrors.max_position_size,
      ).toBeDefined();
    }
  });

  /**
   * Test: non-positive max_daily_loss fails.
   */
  it("should reject zero or negative max_daily_loss", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000,
      max_position_size: 5000,
      max_daily_loss: -100,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.max_daily_loss).toBeDefined();
    }
  });

  /**
   * Test: equity with decimal places fails (must be integer).
   */
  it("should reject decimal equity values", () => {
    const config = {
      deployment_id: "01HDEPLOY123456789012345",
      strategy_build_id: "01HSTRAT123456789012345",
      initial_equity: 10000.5,
      max_position_size: 5000,
      max_daily_loss: 1000,
      max_leverage: 2,
      symbols: ["AAPL"],
    };

    const result = paperTradingConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.initial_equity).toBeDefined();
    }
  });
});
