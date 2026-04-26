/**
 * Paper trading form validation schemas.
 *
 * Purpose:
 *   Define Zod schemas for validating paper trading form inputs.
 *   Schemas enforce domain constraints (min/max values, required fields).
 *
 * Responsibilities:
 *   - Validate field values against domain constraints.
 *   - Provide human-readable error messages.
 *   - Support TypeScript inference for form state.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Make API calls.
 *
 * Dependencies:
 *   - zod: validation library.
 *
 * Error conditions:
 *   - Invalid values trigger schema.parse() errors (caught by form handler).
 *
 * Example:
 *   const result = paperTradingConfigSchema.safeParse(formData);
 *   if (!result.success) {
 *     console.error(result.error.flatten());
 *   }
 */

import { z } from "zod";

/**
 * Schema for paper trading form inputs.
 *
 * Validates:
 * - deployment_id: non-empty string.
 * - strategy_build_id: non-empty string.
 * - initial_equity: number between 1,000 and 1,000,000.
 * - max_position_size: positive number.
 * - max_daily_loss: positive number.
 * - max_leverage: number between 1 and 10 (inclusive).
 * - symbols: non-empty array of non-empty strings.
 */
export const paperTradingConfigSchema = z.object({
  deployment_id: z.string().min(1, "Deployment is required"),
  strategy_build_id: z.string().min(1, "Strategy is required"),
  initial_equity: z
    .number()
    .int("Initial equity must be a whole number")
    .min(1000, "Minimum initial equity is $1,000")
    .max(1000000, "Maximum initial equity is $1,000,000"),
  max_position_size: z.number().positive("Max position size must be greater than 0"),
  max_daily_loss: z.number().positive("Max daily loss must be greater than 0"),
  max_leverage: z.number().min(1, "Minimum leverage is 1x").max(10, "Maximum leverage is 10x"),
  symbols: z
    .array(z.string().min(1, "Symbol cannot be empty"))
    .min(1, "At least one symbol is required"),
});

/**
 * Inferred TypeScript type from the schema.
 *
 * Use this for form state and submission payloads.
 */
export type PaperTradingConfigInput = z.infer<typeof paperTradingConfigSchema>;
