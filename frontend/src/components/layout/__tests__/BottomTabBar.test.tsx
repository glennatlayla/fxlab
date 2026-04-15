/**
 * BottomTabBar component tests.
 *
 * Covers:
 *   - Five tabs are rendered (Home, Runs, Emergency, Alerts, More)
 *   - Home tab links to / route
 *   - Emergency tab has danger (red) styling
 *   - Active tab is highlighted with brand color
 *   - Component is hidden on lg+ screens (lg:hidden class)
 *   - Safe area padding for notch/gesture bar
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { BottomTabBar } from "../BottomTabBar";

// Mock icon exports so we can test what we need without loading Lucide
vi.mock("lucide-react", () => ({
  LayoutDashboard: () => <div data-testid="icon-dashboard">Dashboard</div>,
  Play: () => <div data-testid="icon-play">Play</div>,
  ShieldAlert: () => <div data-testid="icon-shield">Shield</div>,
  Bell: () => <div data-testid="icon-bell">Bell</div>,
  MoreHorizontal: () => <div data-testid="icon-more">More</div>,
}));

// Mock simple pages for routing
const mockPages = {
  home: () => <div data-testid="page-home">Home</div>,
  runs: () => <div data-testid="page-runs">Runs</div>,
  emergency: () => <div data-testid="page-emergency">Emergency</div>,
  alerts: () => <div data-testid="page-alerts">Alerts</div>,
  more: () => <div data-testid="page-more">More</div>,
};

function renderWithRouter(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/" element={mockPages.home()} />
        <Route path="/runs" element={mockPages.runs()} />
        <Route path="/emergency" element={mockPages.emergency()} />
        <Route path="/alerts" element={mockPages.alerts()} />
        <Route path="/more" element={mockPages.more()} />
      </Routes>
      <BottomTabBar />
    </MemoryRouter>,
  );
}

describe("BottomTabBar component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders five tabs with correct labels", () => {
    renderWithRouter();
    // Look for the nav element first, then verify all tabs exist
    const navbar = screen.getByRole("navigation");
    expect(navbar).toBeInTheDocument();
    expect(navbar.textContent).toContain("Home");
    expect(navbar.textContent).toContain("Runs");
    expect(navbar.textContent).toContain("Emergency");
    expect(navbar.textContent).toContain("Alerts");
    expect(navbar.textContent).toContain("More");
  });

  it("home tab links to root path", () => {
    renderWithRouter();
    const homeTab = screen.getByRole("link", { name: /Home/ });
    expect(homeTab).toHaveAttribute("href", "/");
  });

  it("runs tab links to /runs", () => {
    renderWithRouter();
    const runsTab = screen.getByRole("link", { name: /Runs/ });
    expect(runsTab).toHaveAttribute("href", "/runs");
  });

  it("emergency tab links to /emergency", () => {
    renderWithRouter();
    const emergencyTab = screen.getByRole("link", { name: /Emergency/ });
    expect(emergencyTab).toHaveAttribute("href", "/emergency");
  });

  it("alerts tab links to /alerts", () => {
    renderWithRouter();
    const alertsTab = screen.getByRole("link", { name: /Alerts/ });
    expect(alertsTab).toHaveAttribute("href", "/alerts");
  });

  it("more tab links to /more", () => {
    renderWithRouter();
    const moreTab = screen.getByRole("link", { name: /More/ });
    expect(moreTab).toHaveAttribute("href", "/more");
  });

  it("emergency tab has danger styling (red color)", () => {
    renderWithRouter();
    const emergencyTab = screen.getByRole("link", { name: /Emergency/ });
    // The emergency tab should have text-danger-500 class for red icon
    expect(emergencyTab).toHaveClass("text-danger-500");
  });

  it("active tab is highlighted with brand color", () => {
    renderWithRouter("/runs");
    const runsTab = screen.getByRole("link", { name: /Runs/ });
    // Active tabs should have text-brand-600
    expect(runsTab).toHaveClass("text-brand-600");
  });

  it("inactive tab has neutral color", () => {
    renderWithRouter("/runs");
    const homeTab = screen.getByRole("link", { name: /Home/ });
    // Inactive tabs should have text-surface-400
    expect(homeTab).toHaveClass("text-surface-400");
  });

  it("has lg:hidden class so it's hidden on large screens", () => {
    renderWithRouter();
    const navbar = screen.getByRole("navigation");
    expect(navbar).toHaveClass("lg:hidden");
  });

  it("has fixed positioning and spans full width", () => {
    renderWithRouter();
    const navbar = screen.getByRole("navigation");
    expect(navbar).toHaveClass("fixed", "bottom-0", "left-0", "right-0");
  });

  it("has z-30 for proper stacking context", () => {
    renderWithRouter();
    const navbar = screen.getByRole("navigation");
    expect(navbar).toHaveClass("z-30");
  });

  it("includes safe area padding for device notches", () => {
    renderWithRouter();
    const navbar = screen.getByRole("navigation");
    expect(navbar).toHaveClass("pb-[env(safe-area-inset-bottom)]");
  });

  it("has correct height class", () => {
    renderWithRouter();
    const navbar = screen.getByRole("navigation");
    expect(navbar).toHaveClass("h-16");
  });

  it("renders all icons", () => {
    renderWithRouter();
    expect(screen.getByTestId("icon-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("icon-play")).toBeInTheDocument();
    expect(screen.getByTestId("icon-shield")).toBeInTheDocument();
    expect(screen.getByTestId("icon-bell")).toBeInTheDocument();
    expect(screen.getByTestId("icon-more")).toBeInTheDocument();
  });

  it("each tab is a NavLink component for proper routing", async () => {
    const user = userEvent.setup();
    renderWithRouter("/");

    // Verify home page is shown
    expect(screen.getByTestId("page-home")).toBeInTheDocument();

    // Click runs tab
    const runsTab = screen.getByRole("link", { name: /Runs/ });
    await user.click(runsTab);

    // Verify runs page is shown (routing worked)
    expect(screen.getByTestId("page-runs")).toBeInTheDocument();
  });
});
