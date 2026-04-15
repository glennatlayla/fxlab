/**
 * Tests for UncertaintyExplainer component.
 *
 * Verifies that:
 *   - Severity badges are rendered with correct styling (info, warning, material)
 *   - Plain-language descriptions are displayed for each entry
 *   - "material" entries show danger styling
 *   - "warning" entries show warning styling
 *   - "info" entries show info styling
 *   - Unresolved entries render a resolution form
 *   - Material unresolved entries render BlockerSummary with owner and resolve link
 *   - "resolved" badge is shown for resolved entries
 *
 * Dependencies:
 *   - vitest for assertions and mocking
 *   - @testing-library/react for render and DOM queries
 *   - @testing-library/user-event for user interactions
 *   - React component: UncertaintyExplainer
 */

import { render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import type { UncertaintyEntry } from "@/types/strategy";
import { UncertaintyExplainer } from "./UncertaintyExplainer";

describe("UncertaintyExplainer", () => {
  const mockEntries: UncertaintyEntry[] = [
    {
      id: "unc-1",
      code: "MATERIAL_AMBIGUITY",
      severity: "material",
      title: "Material Ambiguity",
      description: "Entry signal is ambiguous in sideways markets",
      ownerDisplayName: "Alice Chen",
      resolved: false,
      resolutionNote: undefined,
    },
    {
      id: "unc-2",
      code: "PARAM_RANGE_WIDE",
      severity: "warning",
      title: "Parameter Range Too Wide",
      description: "Lookback period range (1–500) may be too broad",
      ownerDisplayName: undefined,
      resolved: false,
      resolutionNote: undefined,
    },
    {
      id: "unc-3",
      code: "LOW_CONFIDENCE_BACKTEST",
      severity: "info",
      title: "Low Confidence Backtest Result",
      description: "Backtest data limited to 6 months of history",
      ownerDisplayName: undefined,
      resolved: true,
      resolutionNote: "Extended with forward testing",
    },
  ];

  describe("severity badge rendering", () => {
    it("renders severity badge for each uncertainty entry", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      expect(screen.getByText("Material Ambiguity")).toBeInTheDocument();
      expect(screen.getByText("Parameter Range Too Wide")).toBeInTheDocument();
      expect(screen.getByText("Low Confidence Backtest Result")).toBeInTheDocument();
    });

    it("renders plain-language description for each entry", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      expect(screen.getByText("Entry signal is ambiguous in sideways markets")).toBeInTheDocument();
      expect(
        screen.getByText("Lookback period range (1–500) may be too broad"),
      ).toBeInTheDocument();
      expect(screen.getByText("Backtest data limited to 6 months of history")).toBeInTheDocument();
    });

    it("shows 'material' severity entries with danger styling", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      const materialEntry = screen.getByText("Material Ambiguity").closest("div");
      expect(materialEntry?.className).toContain("danger");
    });

    it("shows 'warning' entries with warning styling", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      const warningEntry = screen.getByText("Parameter Range Too Wide").closest("div");
      expect(warningEntry?.className).toContain("warning");
    });

    it("shows 'info' entries with info styling", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      const infoEntry = screen.getByText("Low Confidence Backtest Result").closest("div");
      expect(infoEntry?.className).toContain("info");
    });
  });

  describe("resolution state handling", () => {
    it("renders resolution form for unresolved entries", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      // Unresolved entries (unc-1, unc-2) should have a resolution form
      const materialEntry = screen.getByText("Material Ambiguity").closest("div");
      expect(within(materialEntry!).getByRole("button", { name: /resolve/i })).toBeInTheDocument();
    });

    it("material unresolved entry renders BlockerSummary with owner and resolve_uncertainty link", () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      const materialEntry = screen.getByText("Material Ambiguity").closest("div");
      expect(within(materialEntry!).getByText("Alice Chen")).toBeInTheDocument();
      expect(within(materialEntry!).getByRole("link", { name: /resolve/i })).toBeInTheDocument();
      expect(
        within(materialEntry!)
          .getByRole("link", { name: /resolve/i })
          .getAttribute("href"),
      ).toContain("resolve_uncertainty");
    });

    it('renders "resolved" badge when entry is resolved', () => {
      render(<UncertaintyExplainer entries={mockEntries} />);
      const resolvedEntry = screen.getByText("Low Confidence Backtest Result").closest("div");
      expect(within(resolvedEntry!).getByText("resolved")).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("renders empty message when no entries provided", () => {
      render(<UncertaintyExplainer entries={[]} />);
      expect(screen.getByText(/no uncertainties/i)).toBeInTheDocument();
    });
  });
});
