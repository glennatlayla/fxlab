/**
 * useMediaQuery — Reactive CSS media query hook.
 *
 * Purpose:
 *   Subscribe to a CSS media query and return whether it currently matches.
 *   Uses window.matchMedia with an event listener for live updates.
 *
 * Responsibilities:
 *   - Match a CSS media query string and track changes.
 *   - Update component state when media query status changes.
 *   - Clean up listeners on unmount.
 *
 * Does NOT:
 *   - Perform any DOM mutations.
 *   - Make API calls.
 *   - Manage state outside of React.
 *
 * Dependencies:
 *   - React (useState, useEffect).
 *
 * Error conditions:
 *   - Returns false in SSR environments (window undefined).
 *   - Returns false if matchMedia is not supported.
 *
 * Example:
 *   const isDesktop = useMediaQuery("(min-width: 1024px)");
 *   return isDesktop ? <DesktopLayout /> : <MobileLayout />;
 */

import { useState, useEffect } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(false);

  useEffect(() => {
    // SSR-safe: window is undefined in non-browser environments.
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }

    const mediaQueryList = window.matchMedia(query);

    // Set initial state.
    setMatches(mediaQueryList.matches);

    // Create listener for changes.
    const handleChange = (e: MediaQueryListEvent) => {
      setMatches(e.matches);
    };

    // Add listener.
    mediaQueryList.addEventListener("change", handleChange);

    // Cleanup.
    return () => {
      mediaQueryList.removeEventListener("change", handleChange);
    };
  }, [query]);

  return matches;
}

/**
 * useIsMobile — Convenience hook for mobile breakpoint.
 *
 * Returns true if viewport is at most 1023px wide (mobile).
 * Matches Tailwind's lg: breakpoint (1024px).
 *
 * Example:
 *   const isMobile = useIsMobile();
 *   if (isMobile) {
 *     return <MobileMenu />;
 *   }
 */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 1023px)");
}

/**
 * useIsDesktop — Convenience hook for desktop breakpoint.
 *
 * Returns true if viewport is at least 1024px wide (desktop).
 * Matches Tailwind's lg: breakpoint (1024px).
 *
 * Example:
 *   const isDesktop = useIsDesktop();
 *   if (isDesktop) {
 *     return <DesktopSidebar />;
 *   }
 */
export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 1024px)");
}
