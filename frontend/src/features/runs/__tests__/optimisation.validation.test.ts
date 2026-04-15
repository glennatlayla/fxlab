/**
 * Tests for optimisation form validation schema (FE-15).
 *
 * Spec: Zod validation schema for OptimizationFormValues
 * - Validates required backtest fields (symbols, dates, equity)
 * - Validates optimisation metric selection
 * - Validates parameter ranges (at least one, min < max, step > 0)
 * - Validates trial count limits (< 100,000 hard limit)
 * - Validates walk-forward windows (2-20) and train percentage (50-90)
 * - Validates monte carlo run count (≥ 100)
 * - Provides clear error messages
 */

import { describe, it, expect } from "vitest";
import { optimizationFormSchema } from "../optimisation.validation";
import type { OptimizationFormValues } from "../optimisation";

describe("optimizationFormSchema", () => {
  const validBaseForm: OptimizationFormValues = {
    strategy_build_id: "01HSTRATEGY00000000000001",
    symbols: ["AAPL", "MSFT"],
    start_date: "2024-01-01",
    end_date: "2024-12-31",
    interval: "1d",
    initial_equity: 100000,
    optimization_metric: "sharpe_ratio",
    parameters: [
      {
        name: "ma_fast",
        min: 5,
        max: 20,
        step: 5,
      },
    ],
  };

  describe("happy path", () => {
    it("accepts_valid_form", () => {
      const result = optimizationFormSchema.safeParse(validBaseForm);

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data).toEqual(validBaseForm);
      }
    });

    it("accepts_form_with_walk_forward", () => {
      const form = {
        ...validBaseForm,
        walk_forward_windows: 5,
        walk_forward_train_pct: 70,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(true);
    });

    it("accepts_form_with_monte_carlo", () => {
      const form = {
        ...validBaseForm,
        monte_carlo_runs: 1000,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(true);
    });
  });

  describe("backtest field validation", () => {
    it("rejects_missing_symbols", () => {
      const form = {
        ...validBaseForm,
        symbols: [],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.flatten().fieldErrors.symbols).toBeDefined();
      }
    });

    it("rejects_missing_start_date", () => {
      const form = {
        ...validBaseForm,
        start_date: "",
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("rejects_start_date_after_end_date", () => {
      const form = {
        ...validBaseForm,
        start_date: "2024-12-31",
        end_date: "2024-01-01",
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
      if (!result.success) {
        expect(
          result.error.flatten().fieldErrors.start_date ||
            result.error.flatten().fieldErrors.end_date
        ).toBeDefined();
      }
    });

    it("rejects_non_positive_initial_equity", () => {
      const form = {
        ...validBaseForm,
        initial_equity: 0,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("rejects_invalid_interval", () => {
      const form = {
        ...validBaseForm,
        interval: "invalid",
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });
  });

  describe("optimization metric validation", () => {
    it("accepts_valid_metrics", () => {
      const metrics = [
        "sharpe_ratio",
        "total_return",
        "max_drawdown",
        "win_rate",
        "profit_factor",
      ];

      metrics.forEach((metric) => {
        const form = {
          ...validBaseForm,
          optimization_metric: metric as any,
        };

        const result = optimizationFormSchema.safeParse(form);

        expect(result.success).toBe(true);
      });
    });

    it("rejects_invalid_metric", () => {
      const form = {
        ...validBaseForm,
        optimization_metric: "invalid_metric" as any,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });
  });

  describe("parameter range validation", () => {
    it("rejects_empty_parameters", () => {
      const form = {
        ...validBaseForm,
        parameters: [],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
      if (!result.success) {
        expect(
          result.error.flatten().fieldErrors.parameters
        ).toBeDefined();
      }
    });

    it("rejects_min_greater_than_max", () => {
      const form = {
        ...validBaseForm,
        parameters: [
          {
            name: "ma_fast",
            min: 50,
            max: 10,
            step: 5,
          },
        ],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("rejects_zero_step", () => {
      const form = {
        ...validBaseForm,
        parameters: [
          {
            name: "ma_fast",
            min: 5,
            max: 20,
            step: 0,
          },
        ],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("rejects_negative_step", () => {
      const form = {
        ...validBaseForm,
        parameters: [
          {
            name: "ma_fast",
            min: 5,
            max: 20,
            step: -1,
          },
        ],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("accepts_multiple_parameters", () => {
      const form = {
        ...validBaseForm,
        parameters: [
          {
            name: "ma_fast",
            min: 5,
            max: 20,
            step: 5,
          },
          {
            name: "ma_slow",
            min: 20,
            max: 50,
            step: 10,
          },
        ],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(true);
    });
  });

  describe("trial count validation", () => {
    it("rejects_trial_count_over_hard_limit", () => {
      // Create a parameter combination that exceeds 100,000 trials
      // 1 to 100,001 step 1 = 100,001 combinations
      const form = {
        ...validBaseForm,
        parameters: [
          {
            name: "param1",
            min: 1,
            max: 100001,
            step: 1,
          },
        ],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("accepts_trial_count_under_hard_limit", () => {
      const form = {
        ...validBaseForm,
        parameters: [
          {
            name: "param1",
            min: 1,
            max: 100,
            step: 10,
          },
        ],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(true);
    });
  });

  describe("walk-forward validation", () => {
    it("rejects_walk_forward_windows_below_minimum", () => {
      const form = {
        ...validBaseForm,
        walk_forward_windows: 1,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("rejects_walk_forward_windows_above_maximum", () => {
      const form = {
        ...validBaseForm,
        walk_forward_windows: 21,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("accepts_walk_forward_windows_in_range", () => {
      [2, 5, 10, 20].forEach((windows) => {
        const form = {
          ...validBaseForm,
          walk_forward_windows: windows,
        };

        const result = optimizationFormSchema.safeParse(form);

        expect(result.success).toBe(true);
      });
    });

    it("rejects_train_percentage_below_minimum", () => {
      const form = {
        ...validBaseForm,
        walk_forward_train_pct: 40,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("rejects_train_percentage_above_maximum", () => {
      const form = {
        ...validBaseForm,
        walk_forward_train_pct: 95,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("accepts_train_percentage_in_range", () => {
      [50, 60, 70, 80, 90].forEach((pct) => {
        const form = {
          ...validBaseForm,
          walk_forward_train_pct: pct,
        };

        const result = optimizationFormSchema.safeParse(form);

        expect(result.success).toBe(true);
      });
    });
  });

  describe("monte-carlo validation", () => {
    it("rejects_monte_carlo_runs_below_minimum", () => {
      const form = {
        ...validBaseForm,
        monte_carlo_runs: 50,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });

    it("accepts_monte_carlo_runs_above_minimum", () => {
      [100, 500, 1000, 5000].forEach((runs) => {
        const form = {
          ...validBaseForm,
          monte_carlo_runs: runs,
        };

        const result = optimizationFormSchema.safeParse(form);

        expect(result.success).toBe(true);
      });
    });

    it("rejects_non_integer_monte_carlo_runs", () => {
      const form = {
        ...validBaseForm,
        monte_carlo_runs: 500.5,
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
    });
  });

  describe("error messages", () => {
    it("provides_clear_error_messages", () => {
      const form = {
        ...validBaseForm,
        symbols: [],
        parameters: [],
      };

      const result = optimizationFormSchema.safeParse(form);

      expect(result.success).toBe(false);
      if (!result.success) {
        const errors = result.error.flatten();
        expect(errors.fieldErrors.symbols).toBeDefined();
        expect(errors.fieldErrors.parameters).toBeDefined();
      }
    });
  });
});
