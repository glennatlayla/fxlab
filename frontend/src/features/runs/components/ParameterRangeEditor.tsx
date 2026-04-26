/**
 * ParameterRangeEditor component for optimization form (FE-15).
 *
 * Purpose:
 * - Edit min/max/step for parameter ranges
 * - Show combination count per parameter
 * - Add/remove parameters
 * - Validate ranges (min < max, step > 0)
 * - Provide inline error feedback
 *
 * Responsibilities:
 * - Render parameter range input rows
 * - Handle parameter CRUD operations
 * - Perform field-level validation
 * - Propagate changes to parent form
 *
 * Does NOT:
 * - Perform form-level validation (that's the parent's job)
 * - Call APIs
 * - Manage optimization logic
 *
 * Dependencies:
 * - optimisation.ts for domain types and utilities
 * - optimisation.validation.ts for field validation
 * - lucide-react for icons
 * - Tailwind CSS for styling
 *
 * Example:
 *   <ParameterRangeEditor
 *     parameters={formData.parameters}
 *     onChange={(updated) => setFormData({ ...formData, parameters: updated })}
 *   />
 */

import React, { useState, useCallback } from "react";
import { Trash2, Plus } from "lucide-react";
import { validateParameterRange } from "../optimisation.validation";
import type { ParameterRange } from "../optimisation";

export interface ParameterRangeEditorProps {
  /** Current array of parameter ranges. */
  parameters: ParameterRange[];
  /** Callback when parameters change (add/remove/edit). */
  onChange: (updated: ParameterRange[]) => void;
  /** Optional CSS class names. */
  className?: string;
}

/**
 * ParameterRangeEditor — edit parameter grid for optimization.
 *
 * Displays:
 * - One row per parameter with name, min, max, step inputs
 * - Combination count badge per parameter
 * - Add button to add new parameter
 * - Remove button per parameter
 * - Inline validation errors
 *
 * Validates:
 * - min < max
 * - step > 0
 * - Provides error messages on blur
 *
 * Example:
 *   <ParameterRangeEditor
 *     parameters={[
 *       { name: 'ma_fast', min: 5, max: 20, step: 5 }
 *     ]}
 *     onChange={handleParametersChange}
 *   />
 */
export function ParameterRangeEditor({
  parameters,
  onChange,
  className,
}: ParameterRangeEditorProps): React.ReactElement {
  // Track field-level validation errors
  const [errors, setErrors] = useState<Record<number, Record<string, string>>>({});

  const handleAddParameter = useCallback(() => {
    const newParam: ParameterRange = {
      name: "",
      min: 1,
      max: 10,
      step: 1,
    };
    onChange([...parameters, newParam]);
  }, [parameters, onChange]);

  const handleRemoveParameter = useCallback(
    (index: number) => {
      onChange(parameters.filter((_, i) => i !== index));
      setErrors((prev) => {
        const updated = { ...prev };
        delete updated[index];
        return updated;
      });
    },
    [parameters, onChange],
  );

  const handleParameterChange = useCallback(
    (index: number, field: keyof ParameterRange, value: unknown) => {
      const updated = [...parameters];
      updated[index] = {
        ...updated[index],
        [field]: value,
      };
      onChange(updated);
    },
    [parameters, onChange],
  );

  const handleBlur = useCallback(
    (index: number) => {
      // Validate the parameter at this index
      const result = validateParameterRange(parameters[index]);

      if (!result.success) {
        const fieldErrors: Record<string, string> = {};

        // Aggregate errors by field
        Object.entries(result.error.flatten().fieldErrors || {}).forEach(([field, messages]) => {
          if (Array.isArray(messages) && messages.length > 0) {
            fieldErrors[field] = messages[0];
          }
        });

        // Also validate min < max constraint
        if (parameters[index].min >= parameters[index].max) {
          fieldErrors.max = "Min must be less than max";
        }

        setErrors((prev) => ({
          ...prev,
          [index]: fieldErrors,
        }));
      } else {
        // Clear errors for this parameter
        setErrors((prev) => {
          const updated = { ...prev };
          delete updated[index];
          return updated;
        });
      }
    },
    [parameters],
  );

  // Calculate combinations for a single parameter
  const getCombinations = (param: ParameterRange): number => {
    if (param.min >= param.max || param.step <= 0) return 0;
    return Math.ceil((param.max - param.min) / param.step) + 1;
  };

  if (parameters.length === 0) {
    return (
      <div className={`${className || ""}`}>
        <div className="rounded-lg border-2 border-dashed border-gray-300 p-6 text-center">
          <p className="mb-4 text-gray-600">No parameters added</p>
          <button
            type="button"
            onClick={handleAddParameter}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            Add parameter
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`${className || ""} space-y-4`}>
      {/* Parameter rows */}
      {parameters.map((param, index) => {
        const paramErrors = errors[index] || {};
        const combinations = getCombinations(param);

        return (
          <div key={index} className="rounded-lg border border-gray-200 bg-white p-4">
            {/* Parameter name and remove button */}
            <div className="mb-3 flex items-center justify-between">
              <input
                type="text"
                value={param.name}
                onChange={(e) => handleParameterChange(index, "name", e.target.value)}
                placeholder="Parameter name (e.g., ma_fast)"
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                type="button"
                onClick={() => handleRemoveParameter(index)}
                className="ml-3 rounded-lg p-2 text-red-600 transition-colors hover:bg-red-50"
                title="Remove parameter"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            {/* Min, Max, Step inputs */}
            <div className="mb-3 grid grid-cols-3 gap-3">
              {/* Min */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Min</label>
                <input
                  type="number"
                  value={param.min}
                  onChange={(e) =>
                    handleParameterChange(index, "min", parseFloat(e.target.value) || 0)
                  }
                  onBlur={() => handleBlur(index)}
                  className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                    paramErrors.min ? "border-red-500 bg-red-50" : "border-gray-300"
                  }`}
                />
                {paramErrors.min && <p className="mt-1 text-xs text-red-600">{paramErrors.min}</p>}
              </div>

              {/* Max */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Max</label>
                <input
                  type="number"
                  value={param.max}
                  onChange={(e) =>
                    handleParameterChange(index, "max", parseFloat(e.target.value) || 0)
                  }
                  onBlur={() => handleBlur(index)}
                  className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                    paramErrors.max || paramErrors.min
                      ? "border-red-500 bg-red-50"
                      : "border-gray-300"
                  }`}
                />
                {paramErrors.max && <p className="mt-1 text-xs text-red-600">{paramErrors.max}</p>}
              </div>

              {/* Step */}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Step</label>
                <input
                  type="number"
                  value={param.step}
                  onChange={(e) =>
                    handleParameterChange(index, "step", parseFloat(e.target.value) || 0)
                  }
                  onBlur={() => handleBlur(index)}
                  step="any"
                  className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                    paramErrors.step ? "border-red-500 bg-red-50" : "border-gray-300"
                  }`}
                />
                {paramErrors.step && (
                  <p className="mt-1 text-xs text-red-600">{paramErrors.step}</p>
                )}
              </div>
            </div>

            {/* Combinations badge */}
            {combinations > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600">
                  {combinations} combination{combinations !== 1 ? "s" : ""}
                </span>
                <span className="inline-block rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
                  {combinations}
                </span>
              </div>
            )}
          </div>
        );
      })}

      {/* Add parameter button */}
      <button
        type="button"
        onClick={handleAddParameter}
        className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 px-4 py-3 text-sm font-medium text-gray-700 transition-colors hover:border-blue-400 hover:bg-blue-50 hover:text-blue-600"
      >
        <Plus className="h-4 w-4" />
        Add parameter
      </button>
    </div>
  );
}
