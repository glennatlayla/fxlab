/**
 * Tests for CompilationStatus component.
 *
 * Verifies that:
 *   - Stage labels are rendered for all compilation stages
 *   - A spinner is shown for "running" stages
 *   - A checkmark icon is shown for "completed" stages
 *   - An X icon is shown for "failed" stages
 *   - Error messages are displayed for failed stages
 *   - Duration in milliseconds is shown for completed stages
 *   - Overall status is displayed (pending, running, completed, failed)
 *
 * Dependencies:
 *   - vitest for assertions
 *   - @testing-library/react for render and DOM queries
 *   - React component: CompilationStatus
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import type { CompilationRun } from "@/types/strategy";
import { CompilationStatus } from "./CompilationStatus";

describe("CompilationStatus", () => {
  const mockCompilationRun: CompilationRun = {
    id: "compile-run-1",
    strategyId: "strategy-1",
    startedAt: "2026-04-04T10:00:00Z",
    completedAt: "2026-04-04T10:00:05Z",
    overallStatus: "completed",
    stages: [
      {
        name: "parse",
        label: "Parse",
        status: "completed",
        durationMs: 100,
        error: undefined,
      },
      {
        name: "validate",
        label: "Validate",
        status: "completed",
        durationMs: 500,
        error: undefined,
      },
      {
        name: "compile",
        label: "Compile",
        status: "completed",
        durationMs: 1200,
        error: undefined,
      },
      {
        name: "package",
        label: "Package",
        status: "completed",
        durationMs: 300,
        error: undefined,
      },
    ],
  };

  describe("stage rendering", () => {
    it("renders stage labels for all compilation stages", () => {
      render(<CompilationStatus compilation={mockCompilationRun} />);
      expect(screen.getByText("Parse")).toBeInTheDocument();
      expect(screen.getByText("Validate")).toBeInTheDocument();
      expect(screen.getByText("Compile")).toBeInTheDocument();
      expect(screen.getByText("Package")).toBeInTheDocument();
    });

    it("shows spinner for 'running' stage", () => {
      const runningCompilation: CompilationRun = {
        ...mockCompilationRun,
        overallStatus: "running",
        stages: [
          { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
          { name: "validate", label: "Validate", status: "running", durationMs: undefined },
          { name: "compile", label: "Compile", status: "pending" },
          { name: "package", label: "Package", status: "pending" },
        ],
      };
      render(<CompilationStatus compilation={runningCompilation} />);
      // Spinner should be shown in or near the Validate stage
      const validateStage = screen.getByText("Validate").closest("div");
      expect(validateStage?.querySelector("svg[class*='animate']")).toBeInTheDocument();
    });

    it("shows checkmark for 'completed' stage", () => {
      render(<CompilationStatus compilation={mockCompilationRun} />);
      // Each completed stage should have a checkmark icon
      const parseStage = screen.getByText("Parse").closest("div");
      expect(parseStage?.querySelector("svg[class*='check']")).toBeInTheDocument();
    });

    it("shows X icon for 'failed' stage", () => {
      const failedCompilation: CompilationRun = {
        ...mockCompilationRun,
        overallStatus: "failed",
        stages: [
          { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
          {
            name: "validate",
            label: "Validate",
            status: "failed",
            durationMs: 150,
            error: "Schema validation failed: missing required field 'entryCondition'",
          },
          { name: "compile", label: "Compile", status: "skipped" },
          { name: "package", label: "Package", status: "skipped" },
        ],
      };
      render(<CompilationStatus compilation={failedCompilation} />);
      const validateStage = screen.getByText("Validate").closest("div");
      expect(validateStage?.querySelector("svg[class*='x']")).toBeInTheDocument();
    });

    it("shows error message for failed stages", () => {
      const failedCompilation: CompilationRun = {
        ...mockCompilationRun,
        overallStatus: "failed",
        stages: [
          { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
          {
            name: "validate",
            label: "Validate",
            status: "failed",
            durationMs: 150,
            error: "Schema validation failed: missing required field 'entryCondition'",
          },
          { name: "compile", label: "Compile", status: "skipped" },
          { name: "package", label: "Package", status: "skipped" },
        ],
      };
      render(<CompilationStatus compilation={failedCompilation} />);
      expect(screen.getByText(/Schema validation failed/)).toBeInTheDocument();
    });

    it("shows duration for completed stages", () => {
      render(<CompilationStatus compilation={mockCompilationRun} />);
      expect(screen.getByText(/100\s*ms/)).toBeInTheDocument(); // Parse stage
      expect(screen.getByText(/500\s*ms/)).toBeInTheDocument(); // Validate stage
      expect(screen.getByText(/1200\s*ms/)).toBeInTheDocument(); // Compile stage
    });

    it("shows overall status", () => {
      render(<CompilationStatus compilation={mockCompilationRun} />);
      expect(screen.getByText(/overall.*completed/i)).toBeInTheDocument();
    });

    it("shows 'running' overall status while compilation is in progress", () => {
      const runningCompilation: CompilationRun = {
        ...mockCompilationRun,
        completedAt: undefined,
        overallStatus: "running",
        stages: [
          { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
          { name: "validate", label: "Validate", status: "running", durationMs: undefined },
          { name: "compile", label: "Compile", status: "pending" },
          { name: "package", label: "Package", status: "pending" },
        ],
      };
      render(<CompilationStatus compilation={runningCompilation} />);
      expect(screen.getByText(/overall.*running/i)).toBeInTheDocument();
    });

    it("shows 'failed' overall status when any stage fails", () => {
      const failedCompilation: CompilationRun = {
        ...mockCompilationRun,
        overallStatus: "failed",
        stages: [
          { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
          {
            name: "validate",
            label: "Validate",
            status: "failed",
            durationMs: 150,
            error: "Validation error",
          },
          { name: "compile", label: "Compile", status: "skipped" },
          { name: "package", label: "Package", status: "skipped" },
        ],
      };
      render(<CompilationStatus compilation={failedCompilation} />);
      expect(screen.getByText(/overall.*failed/i)).toBeInTheDocument();
    });
  });

  describe("skipped stages", () => {
    it("renders skipped stages with appropriate styling", () => {
      const failedCompilation: CompilationRun = {
        ...mockCompilationRun,
        overallStatus: "failed",
        stages: [
          { name: "parse", label: "Parse", status: "completed", durationMs: 100 },
          {
            name: "validate",
            label: "Validate",
            status: "failed",
            durationMs: 150,
            error: "Error",
          },
          { name: "compile", label: "Compile", status: "skipped" },
          { name: "package", label: "Package", status: "skipped" },
        ],
      };
      render(<CompilationStatus compilation={failedCompilation} />);
      const compileStage = screen.getByText("Compile").closest("div");
      expect(compileStage?.className).toContain("skipped");
    });
  });

  describe("pending stages", () => {
    it("renders pending stages that have not started", () => {
      const pendingCompilation: CompilationRun = {
        ...mockCompilationRun,
        overallStatus: "pending",
        completedAt: undefined,
        stages: [
          { name: "parse", label: "Parse", status: "pending" },
          { name: "validate", label: "Validate", status: "pending" },
          { name: "compile", label: "Compile", status: "pending" },
          { name: "package", label: "Package", status: "pending" },
        ],
      };
      render(<CompilationStatus compilation={pendingCompilation} />);
      expect(screen.getByText(/overall.*pending/i)).toBeInTheDocument();
      expect(screen.getByText("Parse")).toBeInTheDocument();
    });
  });
});
