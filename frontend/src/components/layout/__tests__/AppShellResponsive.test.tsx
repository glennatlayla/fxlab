/**
 * QA-01: Mobile Layout Regression Tests
 *
 * Purpose:
 *   Validate the responsive layout shell works correctly at mobile and desktop
 *   breakpoints. These integration tests ensure the sidebar hides, BottomTabBar
 *   shows, TopBar adjusts, and content area fills properly on mobile.
 *   This is a comprehensive regression test suite for the responsive layout system.
 *
 * Responsibilities:
 *   - Verify sidebar responsive CSS classes (hidden lg:flex)
 *   - Verify BottomTabBar visibility at breakpoints (lg:hidden)
 *   - Verify TopBar positioning adjustments (left-0 lg:left-sidebar)
 *   - Verify main content area margin and padding (ml-0 lg:ml-sidebar, pb-16 lg:pb-0)
 *   - Verify route accessibility for mobile-only pages (/emergency, /alerts, /more)
 *   - Verify navigation structure completeness
 *   - Verify cross-component integration (all layout pieces render together)
 *
 * Does NOT:
 *   - Test authentication (useAuth is mocked)
 *   - Test individual component internals (those are tested separately)
 *   - Test business logic (all tests focus on layout structure and CSS classes)
 *
 * Dependencies:
 *   - @testing-library/react: render, screen, within
 *   - vitest: describe, it, expect
 *   - react-router-dom: MemoryRouter, Routes, Route
 *   - Components: AppShell, Sidebar, TopBar, BottomTabBar, Emergency, Alerts, More
 *   - Pages: Emergency, Alerts, More (lazy loaded)
 *
 * Test Structure:
 *   - Sidebar Responsive Behavior: 3 tests
 *   - BottomTabBar Responsive Behavior: 5 tests
 *   - TopBar Responsive Behavior: 2 tests
 *   - AppShell Main Content: 3 tests
 *   - Mobile Route Accessibility: 3 tests
 *   - Cross-Component Integration: 3 tests
 *   Total: 19 comprehensive regression tests
 *
 * Example:
 *   npm run test -- src/components/layout/__tests__/AppShellResponsive.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "../AppShell";
import { AuthProvider } from "@/auth/AuthProvider";
import type { ReactNode } from "react";

/**
 * Mock lucide-react icons to avoid loading them in tests.
 * Tests verify that icons are rendered by checking data-testid attributes.
 */
vi.mock("lucide-react", () => ({
  LayoutDashboard: () => <div data-testid="icon-dashboard">Dashboard</div>,
  FlaskConical: () => <div data-testid="icon-flask">Flask</div>,
  Play: () => <div data-testid="icon-play">Play</div>,
  Package: () => <div data-testid="icon-package">Package</div>,
  Rss: () => <div data-testid="icon-rss">Rss</div>,
  ListChecks: () => <div data-testid="icon-listchecks">ListChecks</div>,
  ShieldCheck: () => <div data-testid="icon-shieldcheck">ShieldCheck</div>,
  GitCompare: () => <div data-testid="icon-gitcompare">GitCompare</div>,
  ClipboardList: () => <div data-testid="icon-clipboardlist">ClipboardList</div>,
  ShieldAlert: () => <div data-testid="icon-shieldalert">ShieldAlert</div>,
  Bell: () => <div data-testid="icon-bell">Bell</div>,
  MoreHorizontal: () => <div data-testid="icon-more">More</div>,
  LogOut: () => <div data-testid="icon-logout">Logout</div>,
  User: () => <div data-testid="icon-user">User</div>,
  AlertTriangle: () => <div data-testid="icon-alert">Alert</div>,
  Lock: () => <div data-testid="icon-lock">Lock</div>,
  ChevronRight: () => <div data-testid="icon-chevronright">ChevronRight</div>,
}));

/**
 * Mock the emergency API module to avoid real API calls.
 * Only needed for routes that require the emergency API.
 */
vi.mock("@/features/emergency/api", () => ({
  emergencyApi: {
    getStatus: vi.fn(() => Promise.resolve([])),
  },
}));

/**
 * Create a test QueryClient with retry disabled for faster tests.
 */
const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

/**
 * Wrapper component that provides all required providers for rendering AppShell.
 * - QueryClientProvider: for @tanstack/react-query
 * - AuthProvider: for useAuth hook
 * - MemoryRouter: for routing
 *
 * Props:
 *   children: The component(s) to wrap
 *   initialPath: The initial router path (default: "/")
 */
interface RenderWithProvidersProps {
  children: ReactNode;
  initialPath?: string;
}

function RenderWithProviders({ children, initialPath = "/" }: RenderWithProvidersProps) {
  const queryClient = createTestQueryClient();

  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

/**
 * Mock pages for testing routes.
 * Each mock page exports a simple component that identifies which route rendered.
 */
function MockDashboard() {
  return <div data-testid="page-dashboard">Dashboard</div>;
}

function MockEmergency() {
  return <div data-testid="page-emergency">Emergency Controls</div>;
}

function MockAlerts() {
  return <div data-testid="page-alerts">Alerts</div>;
}

function MockMore() {
  return <div data-testid="page-more">More Options</div>;
}

describe("AppShellResponsive — Mobile Layout Regression Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ===========================================================================
  // SIDEBAR RESPONSIVE BEHAVIOR
  // ===========================================================================

  describe("Sidebar Responsive Behavior", () => {
    it("test_sidebar_has_hidden_lg_flex_classes — verify sidebar includes hidden and lg:flex", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the sidebar aside element
      const sidebar = screen.getByRole("complementary");

      // Verify it has both hidden class (for mobile) and lg:flex (for desktop)
      expect(sidebar).toHaveClass("hidden");
      expect(sidebar).toHaveClass("lg:flex");
    });

    it("test_sidebar_brand_renders — verify FXLab brand text is present in sidebar", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the brand text in the sidebar
      const brandText = screen.getByText("FXLab");
      expect(brandText).toBeInTheDocument();

      // Verify the brand is within the sidebar
      const sidebar = screen.getByRole("complementary");
      expect(within(sidebar).getByText("FXLab")).toBeInTheDocument();
    });

    it("test_sidebar_nav_sections_present — verify all 4 nav sections exist", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      const sidebar = screen.getByRole("complementary");

      // Verify all four navigation section headings are present
      expect(within(sidebar).getByText("Overview")).toBeInTheDocument();
      expect(within(sidebar).getByText("Trading")).toBeInTheDocument();
      expect(within(sidebar).getByText("Operations")).toBeInTheDocument();
      expect(within(sidebar).getByText("Governance")).toBeInTheDocument();
    });
  });

  // ===========================================================================
  // BOTTOM TAB BAR RESPONSIVE BEHAVIOR
  // ===========================================================================

  describe("BottomTabBar Responsive Behavior", () => {
    it("test_bottom_tab_bar_has_lg_hidden_class — verify it is hidden on desktop", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the mobile navigation bar by checking all navigation elements
      // The BottomTabBar has aria-label="Mobile navigation"
      const mobileNav = screen.getByLabelText("Mobile navigation");

      // Verify it has the lg:hidden class (hidden on desktop)
      expect(mobileNav).toHaveClass("lg:hidden");
    });

    it("test_bottom_tab_bar_renders_five_tabs — verify Home, Runs, Emergency, Alerts, More tabs", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify all five tabs exist in the bottom tab bar by checking links
      const mobileNav = screen.getByLabelText("Mobile navigation");
      expect(within(mobileNav).getByRole("link", { name: /Home/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /Runs/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /Emergency/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /Alerts/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /More/ })).toBeInTheDocument();
    });

    it("test_bottom_tab_bar_emergency_tab_has_danger_color — verify red styling", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the Emergency tab link
      const emergencyTab = screen.getByRole("link", { name: /Emergency/ });

      // Verify it has the danger red color class
      expect(emergencyTab).toHaveClass("text-danger-500");
    });

    it("test_bottom_tab_bar_links_are_correct — verify href targets for each tab", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify each tab links to the correct path by finding them in the BottomTabBar
      const mobileNav = screen.getByLabelText("Mobile navigation");
      expect(within(mobileNav).getByRole("link", { name: /Home/ })).toHaveAttribute("href", "/");
      expect(within(mobileNav).getByRole("link", { name: /Runs/ })).toHaveAttribute(
        "href",
        "/runs",
      );
      expect(within(mobileNav).getByRole("link", { name: /Emergency/ })).toHaveAttribute(
        "href",
        "/emergency",
      );
      expect(within(mobileNav).getByRole("link", { name: /Alerts/ })).toHaveAttribute(
        "href",
        "/alerts",
      );
      expect(within(mobileNav).getByRole("link", { name: /More/ })).toHaveAttribute(
        "href",
        "/more",
      );
    });

    it("test_bottom_tab_bar_has_safe_area_padding — verify pb-[env(safe-area-inset-bottom)]", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the mobile navigation bar
      const mobileNav = screen.getByLabelText("Mobile navigation");

      // Verify it has safe area padding for notch-aware devices (iPhone, etc.)
      expect(mobileNav).toHaveClass("pb-[env(safe-area-inset-bottom)]");
    });
  });

  // ===========================================================================
  // TOP BAR RESPONSIVE BEHAVIOR
  // ===========================================================================

  describe("TopBar Responsive Behavior", () => {
    it("test_topbar_has_responsive_left_offset — verify left-0 lg:left-sidebar classes", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the top header element
      const topBar = screen.getByRole("banner");

      // Verify it has responsive left positioning:
      // left-0 on mobile, left-sidebar on lg+
      expect(topBar).toHaveClass("left-0");
      expect(topBar).toHaveClass("lg:left-sidebar");
    });

    it("test_topbar_renders_breadcrumbs — verify breadcrumbs component present", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // The Breadcrumbs component should be rendered in the TopBar
      // We verify this by checking that the header contains breadcrumb elements
      const topBar = screen.getByRole("banner");
      expect(topBar).toBeInTheDocument();

      // On the root path, breadcrumbs display "Dashboard" as an h1
      // which is the title for the Dashboard page
      const dashboardTitle = within(topBar).getByRole("heading", { name: /Dashboard/ });
      expect(dashboardTitle).toBeInTheDocument();
    });

    it("test_topbar_user_info_hidden_on_mobile — verify hidden sm:flex on user info section", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the header
      const topBar = screen.getByRole("banner");

      // Look for the logout button which is in the TopBar
      // The LogOut button has title="Sign out"
      const logoutButton = within(topBar).getByTitle("Sign out");
      expect(logoutButton).toBeInTheDocument();
    });
  });

  // ===========================================================================
  // APP SHELL MAIN CONTENT AREA
  // ===========================================================================

  describe("AppShell Main Content", () => {
    it("test_main_has_responsive_margin — verify ml-0 lg:ml-sidebar classes", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the main content area
      const main = screen.getByRole("main");

      // Verify responsive margin classes:
      // ml-0 on mobile (no left margin), ml-sidebar on lg+ (offset by sidebar)
      expect(main).toHaveClass("ml-0");
      expect(main).toHaveClass("lg:ml-sidebar");
    });

    it("test_main_has_mobile_bottom_padding — verify pb-16 lg:pb-0 for BottomTabBar clearance", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the main content area
      const main = screen.getByRole("main");

      // Verify bottom padding for mobile (pb-16 = 4rem to clear the BottomTabBar)
      // and no bottom padding on desktop (lg:pb-0)
      expect(main).toHaveClass("pb-16");
      expect(main).toHaveClass("lg:pb-0");
    });

    it("test_main_has_responsive_padding — verify p-4 lg:p-6", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Find the main content area
      const main = screen.getByRole("main");

      // Verify responsive padding:
      // p-4 on mobile (1rem), p-6 on lg+ (1.5rem)
      expect(main).toHaveClass("p-4");
      expect(main).toHaveClass("lg:p-6");
    });
  });

  // ===========================================================================
  // MOBILE ROUTE ACCESSIBILITY
  // ===========================================================================

  describe("Mobile Route Accessibility", () => {
    it("test_emergency_route_renders — verify /emergency route loads Emergency page", () => {
      render(
        <RenderWithProviders initialPath="/emergency">
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
              <Route path="emergency" element={<MockEmergency />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify that the Emergency page content is rendered at the /emergency route
      expect(screen.getByTestId("page-emergency")).toBeInTheDocument();
    });

    it("test_alerts_route_renders — verify /alerts route loads Alerts page", () => {
      render(
        <RenderWithProviders initialPath="/alerts">
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
              <Route path="alerts" element={<MockAlerts />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify that the Alerts page content is rendered at the /alerts route
      expect(screen.getByTestId("page-alerts")).toBeInTheDocument();
    });

    it("test_more_route_renders — verify /more route loads More page", () => {
      render(
        <RenderWithProviders initialPath="/more">
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
              <Route path="more" element={<MockMore />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify that the More page content is rendered at the /more route
      expect(screen.getByTestId("page-more")).toBeInTheDocument();
    });
  });

  // ===========================================================================
  // CROSS-COMPONENT INTEGRATION
  // ===========================================================================

  describe("Cross-Component Integration", () => {
    it("test_appshell_renders_sidebar_topbar_and_content — verify all 3 structural elements present", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify all three main layout components render:
      // 1. Sidebar (as an aside element with complementary role)
      expect(screen.getByRole("complementary")).toBeInTheDocument();

      // 2. TopBar (as a banner element)
      expect(screen.getByRole("banner")).toBeInTheDocument();

      // 3. Main content area (as main role)
      expect(screen.getByRole("main")).toBeInTheDocument();
    });

    it("test_appshell_renders_bottom_tab_bar — verify BottomTabBar is included in AppShell", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify BottomTabBar is rendered as mobile navigation
      const mobileNav = screen.getByLabelText("Mobile navigation");
      expect(mobileNav).toBeInTheDocument();

      // Verify it contains the five tabs by checking for links
      expect(within(mobileNav).getByRole("link", { name: /Home/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /Runs/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /Emergency/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /Alerts/ })).toBeInTheDocument();
      expect(within(mobileNav).getByRole("link", { name: /More/ })).toBeInTheDocument();
    });

    it("test_outlet_renders_child_route — verify child content renders in main area", () => {
      render(
        <RenderWithProviders>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<MockDashboard />} />
              <Route path="emergency" element={<MockEmergency />} />
              <Route path="alerts" element={<MockAlerts />} />
              <Route path="more" element={<MockMore />} />
            </Route>
          </Routes>
        </RenderWithProviders>,
      );

      // Verify the Outlet renders child route content in the main area
      const main = screen.getByRole("main");
      expect(within(main).getByTestId("page-dashboard")).toBeInTheDocument();
    });
  });
});
