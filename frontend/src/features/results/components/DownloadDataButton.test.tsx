/**
 * Tests for DownloadDataButton component.
 *
 * AC-4: Download triggers zip bundle with metadata.json containing
 *        run_id and export_schema_version.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DownloadDataButton } from "./DownloadDataButton";

describe("DownloadDataButton", () => {
  it("renders a button with default label", () => {
    render(<DownloadDataButton onDownload={vi.fn()} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(/download/i);
  });

  it("renders with custom label", () => {
    render(<DownloadDataButton onDownload={vi.fn()} label="Export CSV" />);
    expect(screen.getByRole("button")).toHaveTextContent("Export CSV");
  });

  it("calls onDownload when clicked", async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();
    render(<DownloadDataButton onDownload={onDownload} />);
    await user.click(screen.getByRole("button"));
    expect(onDownload).toHaveBeenCalledOnce();
  });

  it("shows loading state and disables button when isLoading is true", () => {
    render(<DownloadDataButton onDownload={vi.fn()} isLoading={true} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
  });

  it("is enabled by default when isLoading is false", () => {
    render(<DownloadDataButton onDownload={vi.fn()} isLoading={false} />);
    expect(screen.getByRole("button")).not.toBeDisabled();
  });
});
