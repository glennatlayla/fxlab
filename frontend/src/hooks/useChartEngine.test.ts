/**
 * Tests for useChartEngine hook.
 *
 * Acceptance criteria (M22):
 *   - useChartEngine(400) returns "recharts"
 *   - useChartEngine(600) returns "echarts"
 *   - Threshold boundary (500) selects "echarts"
 */

import { renderHook } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useChartEngine } from "./useChartEngine";

describe("useChartEngine", () => {
  it("returns 'recharts' for small datasets (400 points)", () => {
    const { result } = renderHook(() => useChartEngine(400));
    expect(result.current).toBe("recharts");
  });

  it("returns 'echarts' for large datasets (600 points)", () => {
    const { result } = renderHook(() => useChartEngine(600));
    expect(result.current).toBe("echarts");
  });

  it("returns 'recharts' for zero data points", () => {
    const { result } = renderHook(() => useChartEngine(0));
    expect(result.current).toBe("recharts");
  });

  it("returns 'recharts' for 499 points (just below threshold)", () => {
    const { result } = renderHook(() => useChartEngine(499));
    expect(result.current).toBe("recharts");
  });

  it("returns 'echarts' for exactly 500 points (at threshold)", () => {
    const { result } = renderHook(() => useChartEngine(500));
    expect(result.current).toBe("echarts");
  });
});
