/**
 * Tailwind theme — the single source of design tokens (Standards §5: tokens
 * centralized, not inlined per component). Every colour resolves to a CSS
 * variable defined in src/index.css, so components reference semantic class
 * names (bg-surface, text-foreground, bg-status-pass-bg, …) and never raw hex.
 * Light mode only.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--color-background)",
        surface: "var(--color-surface)",
        border: "var(--color-border)",
        foreground: "var(--color-foreground)",
        "muted-foreground": "var(--color-muted-foreground)",
        accent: {
          DEFAULT: "var(--color-accent)",
          hover: "var(--color-accent-hover)",
          foreground: "var(--color-accent-foreground)",
        },
        status: {
          "pass-bg": "var(--color-status-pass-bg)",
          "pass-fg": "var(--color-status-pass-fg)",
          "pass-solid": "var(--color-status-pass-solid)",
          "fail-bg": "var(--color-status-fail-bg)",
          "fail-fg": "var(--color-status-fail-fg)",
          "fail-solid": "var(--color-status-fail-solid)",
          "flaky-bg": "var(--color-status-flaky-bg)",
          "flaky-fg": "var(--color-status-flaky-fg)",
          "flaky-solid": "var(--color-status-flaky-solid)",
          "info-bg": "var(--color-status-info-bg)",
          "info-fg": "var(--color-status-info-fg)",
          "info-solid": "var(--color-status-info-solid)",
          "neutral-bg": "var(--color-status-neutral-bg)",
          "neutral-fg": "var(--color-status-neutral-fg)",
          "neutral-solid": "var(--color-status-neutral-solid)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
