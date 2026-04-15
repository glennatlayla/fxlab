/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
        "src/**/*.spec.{ts,tsx}",
        "src/main.tsx",
        "src/vite-env.d.ts",
        // Exclude placeholder pages for milestones not yet implemented (M26–M31).
        // Coverage for these is tracked when the respective milestone is built.
        "src/pages/Approvals.tsx",
        "src/pages/Artifacts.tsx",
        "src/pages/Audit.tsx",
        "src/pages/Dashboard.tsx",
        "src/pages/Feeds.tsx",
        "src/pages/Overrides.tsx",
        "src/pages/Queues.tsx",
        "src/pages/Runs.tsx",
        "src/pages/RunReadiness.tsx",
        // Exclude layout components pending M22+ layout tests
        "src/components/layout/**",
        // AuthGuard and banners pending dedicated test coverage
        "src/components/auth/AuthGuard.tsx",
        "src/components/ui/DraftRecoveryBanner.tsx",
        "src/components/ui/ServerSideBanner.tsx",
        // StrategyStudio page wiring — tested via integration tests
        "src/pages/StrategyStudio.tsx",
      ],
      thresholds: {
        statements: 80,
        branches: 65,
        functions: 80,
        lines: 80,
      },
    },
  },
});
