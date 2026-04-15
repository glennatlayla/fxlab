/**
 * Tests for Results Explorer constants module.
 *
 * Verifies that all constants have correct values and types.
 * Prevents accidental changes to values that affect rendering,
 * API retry behaviour, and download safety.
 */

import { describe, it, expect } from "vitest";
import {
  EQUITY_CHART_HEIGHT,
  DRAWDOWN_CHART_HEIGHT,
  COLOR_EQUITY_LINE,
  COLOR_DRAWDOWN_STROKE,
  COLOR_DRAWDOWN_FILL,
  TRADE_BLOTTER_ROW_HEIGHT,
  TRADE_BLOTTER_VIEWPORT_HEIGHT,
  TRADE_BLOTTER_OVERSCAN,
  TRIAL_TABLE_ROW_HEIGHT,
  TRIAL_TABLE_VIEWPORT_HEIGHT,
  TRIAL_TABLE_OVERSCAN,
  API_MAX_RETRIES,
  API_RETRY_BASE_DELAY_MS,
  API_JITTER_FACTOR,
  DOWNLOAD_TIMEOUT_MS,
  BLOB_REVOKE_DELAY_MS,
  EXPORT_BLOB_MIME_TYPE,
  CANDIDATE_TABLE_ROW_HEIGHT,
  CANDIDATE_TABLE_VIEWPORT_HEIGHT,
  CANDIDATE_TABLE_OVERSCAN,
  TRADE_BLOTTER_COLUMNS,
  TRIAL_TABLE_COLUMNS,
  CANDIDATE_TABLE_COLUMNS,
  OP_FETCH_RUN_CHARTS,
  OP_DOWNLOAD_EXPORT,
  OP_FILTER_TRADES,
  OP_RENDER_PAGE,
} from "./constants";

describe("Results Explorer constants", () => {
  // -------------------------------------------------------------------------
  // Chart dimensions
  // -------------------------------------------------------------------------

  it("chart dimensions are positive integers", () => {
    expect(EQUITY_CHART_HEIGHT).toBe(320);
    expect(DRAWDOWN_CHART_HEIGHT).toBe(200);
  });

  // -------------------------------------------------------------------------
  // Chart colors
  // -------------------------------------------------------------------------

  it("chart colors are valid hex strings", () => {
    const hexRegex = /^#[0-9a-fA-F]{6}$/;
    expect(COLOR_EQUITY_LINE).toMatch(hexRegex);
    expect(COLOR_DRAWDOWN_STROKE).toMatch(hexRegex);
    expect(COLOR_DRAWDOWN_FILL).toMatch(hexRegex);
  });

  // -------------------------------------------------------------------------
  // Trade blotter layout
  // -------------------------------------------------------------------------

  it("trade blotter layout values are consistent", () => {
    expect(TRADE_BLOTTER_ROW_HEIGHT).toBe(36);
    expect(TRADE_BLOTTER_VIEWPORT_HEIGHT).toBe(400);
    expect(TRADE_BLOTTER_OVERSCAN).toBe(20);
  });

  // -------------------------------------------------------------------------
  // Trial summary table layout
  // -------------------------------------------------------------------------

  it("trial table layout values are consistent", () => {
    expect(TRIAL_TABLE_ROW_HEIGHT).toBe(40);
    expect(TRIAL_TABLE_VIEWPORT_HEIGHT).toBe(480);
    expect(TRIAL_TABLE_OVERSCAN).toBe(10);
  });

  // -------------------------------------------------------------------------
  // Candidate comparison table layout
  // -------------------------------------------------------------------------

  it("candidate table row height is a positive integer", () => {
    expect(CANDIDATE_TABLE_ROW_HEIGHT).toBe(36);
    expect(Number.isInteger(CANDIDATE_TABLE_ROW_HEIGHT)).toBe(true);
  });

  it("candidate table viewport height is a positive integer", () => {
    expect(CANDIDATE_TABLE_VIEWPORT_HEIGHT).toBe(400);
    expect(Number.isInteger(CANDIDATE_TABLE_VIEWPORT_HEIGHT)).toBe(true);
  });

  it("candidate table overscan is a positive integer", () => {
    expect(CANDIDATE_TABLE_OVERSCAN).toBe(10);
    expect(Number.isInteger(CANDIDATE_TABLE_OVERSCAN)).toBe(true);
  });

  // -------------------------------------------------------------------------
  // API & retry
  // -------------------------------------------------------------------------

  it("API retry values are sensible", () => {
    expect(API_MAX_RETRIES).toBeGreaterThanOrEqual(1);
    expect(API_MAX_RETRIES).toBeLessThanOrEqual(5);
    expect(API_RETRY_BASE_DELAY_MS).toBe(1000);
    expect(DOWNLOAD_TIMEOUT_MS).toBe(60_000);
  });

  it("API_JITTER_FACTOR is between 0 and 1 exclusive", () => {
    expect(API_JITTER_FACTOR).toBe(0.25);
    expect(API_JITTER_FACTOR).toBeGreaterThan(0);
    expect(API_JITTER_FACTOR).toBeLessThan(1);
  });

  it("BLOB_REVOKE_DELAY_MS is at least 10 seconds", () => {
    expect(BLOB_REVOKE_DELAY_MS).toBe(30_000);
    expect(BLOB_REVOKE_DELAY_MS).toBeGreaterThanOrEqual(10_000);
  });

  it("EXPORT_BLOB_MIME_TYPE is application/zip", () => {
    expect(EXPORT_BLOB_MIME_TYPE).toBe("application/zip");
  });

  // -------------------------------------------------------------------------
  // Grid column templates
  // -------------------------------------------------------------------------

  it("grid column templates are non-empty strings", () => {
    expect(TRADE_BLOTTER_COLUMNS).toBeTruthy();
    expect(TRIAL_TABLE_COLUMNS).toBeTruthy();
    expect(CANDIDATE_TABLE_COLUMNS).toBeTruthy();
    // Each should contain at least two space-separated column specs.
    expect(TRADE_BLOTTER_COLUMNS.split(" ").length).toBeGreaterThanOrEqual(2);
    expect(TRIAL_TABLE_COLUMNS.split(" ").length).toBeGreaterThanOrEqual(2);
    expect(CANDIDATE_TABLE_COLUMNS.split(" ").length).toBeGreaterThanOrEqual(2);
  });

  // -------------------------------------------------------------------------
  // Logging operation names
  // -------------------------------------------------------------------------

  it("logging operation names follow dot-delimited convention", () => {
    const ops = [OP_FETCH_RUN_CHARTS, OP_DOWNLOAD_EXPORT, OP_FILTER_TRADES, OP_RENDER_PAGE];
    for (const op of ops) {
      expect(op).toMatch(/^results\.\w+$/);
    }
  });

  it("logging operation name values are correct", () => {
    expect(OP_FETCH_RUN_CHARTS).toBe("results.fetch_run_charts");
    expect(OP_DOWNLOAD_EXPORT).toBe("results.download_export_bundle");
    expect(OP_FILTER_TRADES).toBe("results.filter_trades");
    expect(OP_RENDER_PAGE).toBe("results.render_page");
  });
});
