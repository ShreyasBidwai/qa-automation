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
          subtle: "var(--color-accent-subtle)",
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
        // The oracle-trust signature palette (see index.css) — emerald / amber / blue.
        trust: {
          "rule-solid": "var(--color-trust-rule-solid)",
          "rule-bg": "var(--color-trust-rule-bg)",
          "rule-fg": "var(--color-trust-rule-fg)",
          "rule-border": "var(--color-trust-rule-border)",
          "char-solid": "var(--color-trust-char-solid)",
          "char-bg": "var(--color-trust-char-bg)",
          "char-fg": "var(--color-trust-char-fg)",
          "char-border": "var(--color-trust-char-border)",
          "spec-solid": "var(--color-trust-spec-solid)",
          "spec-bg": "var(--color-trust-spec-bg)",
          "spec-fg": "var(--color-trust-spec-fg)",
          "spec-border": "var(--color-trust-spec-border)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        // UI: Inter (design brief). Weights 400/500/600 (600 for headings/wordmark).
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        // Code / paths / IDs / endpoints: JetBrains Mono.
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};
