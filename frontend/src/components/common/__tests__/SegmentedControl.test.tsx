/**
 * Unit tests for SegmentedControl component.
 *
 * Covers rendering, interaction, accessibility, and keyboard navigation.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SegmentedControl } from "../SegmentedControl";

describe("SegmentedControl", () => {
  const defaultOptions = [
    { value: "1m" as const, label: "1m" },
    { value: "5m" as const, label: "5m" },
    { value: "15m" as const, label: "15m" },
  ];

  it("renders all options", () => {
    render(<SegmentedControl options={defaultOptions} value="1m" onChange={() => {}} />);

    expect(screen.getByRole("radio", { name: "1m" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "5m" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "15m" })).toBeInTheDocument();
  });

  it("highlights the active option with aria-pressed", () => {
    render(<SegmentedControl options={defaultOptions} value="5m" onChange={() => {}} />);

    const button5m = screen.getByRole("radio", { name: "5m" });
    expect(button5m).toHaveAttribute("aria-pressed", "true");

    const button1m = screen.getByRole("radio", { name: "1m" });
    expect(button1m).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange when an option is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<SegmentedControl options={defaultOptions} value="1m" onChange={onChange} />);

    const button5m = screen.getByRole("radio", { name: "5m" });
    await user.click(button5m);

    expect(onChange).toHaveBeenCalledWith("5m");
  });

  it("does not call onChange when the active option is clicked again", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<SegmentedControl options={defaultOptions} value="1m" onChange={onChange} />);

    const button1m = screen.getByRole("radio", { name: "1m" });
    await user.click(button1m);

    expect(onChange).not.toHaveBeenCalled();
  });

  it("applies custom className", () => {
    const { container } = render(
      <SegmentedControl
        options={defaultOptions}
        value="1m"
        onChange={() => {}}
        className="custom-class"
      />,
    );

    const control = container.querySelector(".custom-class");
    expect(control).toBeInTheDocument();
  });

  it("is keyboard accessible with Tab navigation", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<SegmentedControl options={defaultOptions} value="1m" onChange={onChange} />);

    // Tab to the first radio
    await user.tab();
    expect(screen.getByRole("radio", { name: "1m" })).toHaveFocus();

    // Tab to next radio
    await user.tab();
    expect(screen.getByRole("radio", { name: "5m" })).toHaveFocus();
  });

  it("allows activation via Enter key", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<SegmentedControl options={defaultOptions} value="1m" onChange={onChange} />);

    const button5m = screen.getByRole("radio", { name: "5m" });
    button5m.focus();
    await user.keyboard("{Enter}");

    expect(onChange).toHaveBeenCalledWith("5m");
  });

  it("allows activation via Space key", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<SegmentedControl options={defaultOptions} value="1m" onChange={onChange} />);

    const button5m = screen.getByRole("radio", { name: "5m" });
    button5m.focus();
    await user.keyboard(" ");

    expect(onChange).toHaveBeenCalledWith("5m");
  });

  it("renders with proper ARIA roles for radio group semantics", () => {
    const { container } = render(
      <SegmentedControl options={defaultOptions} value="1m" onChange={() => {}} />,
    );

    const group = container.querySelector("[role='radiogroup']");
    expect(group).toBeInTheDocument();

    const buttons = screen.getAllByRole("radio");
    expect(buttons).toHaveLength(3);
  });

  it("applies correct styling classes to active and inactive buttons", () => {
    render(<SegmentedControl options={defaultOptions} value="5m" onChange={() => {}} />);

    const activeButton = screen.getByRole("radio", { name: "5m" });
    const inactiveButton = screen.getByRole("radio", { name: "1m" });

    // Active button should have brand color
    expect(activeButton.className).toMatch(/bg-brand-600|brand/);

    // Inactive button should have surface color
    expect(inactiveButton.className).toMatch(/bg-transparent|surface/);
  });
});
