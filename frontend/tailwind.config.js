/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // FXLab brand palette — financial-professional dark theme
        brand: {
          50:  "#eef7ff",
          100: "#d9edff",
          200: "#bce0ff",
          300: "#8eceff",
          400: "#59b2ff",
          500: "#3391ff",  // primary accent
          600: "#1a6ff5",
          700: "#1359e1",
          800: "#1648b6",
          900: "#183e8f",
          950: "#132857",
        },
        surface: {
          0:   "#ffffff",
          50:  "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
          950: "#020617",
        },
        success: "#22c55e",
        warning: "#eab308",
        danger:  "#ef4444",
        info:    "#3b82f6",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
      spacing: {
        "sidebar": "16rem",    // 256px sidebar width
        "topbar":  "3.5rem",   // 56px topbar height
      },
      animation: {
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-in": "slideIn 0.2s ease-out",
        fadeIn: "fadeIn 0.2s ease-out",
        scaleIn: "scaleIn 0.15s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%":   { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideIn: {
          "0%":   { transform: "translateX(-8px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        scaleIn: {
          "0%":   { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
    },
  },
  plugins: [],
};
