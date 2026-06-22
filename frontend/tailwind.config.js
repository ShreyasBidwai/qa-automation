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
        "surface-selected": "var(--color-surface-selected)",
        border: "var(--color-border)",
        "border-subtle": "var(--color-border-subtle)",
        marker: "var(--color-marker)",
        foreground: "var(--color-foreground)",
        "foreground-secondary": "var(--color-foreground-secondary)",
        "muted-foreground": "var(--color-muted-foreground)",
        accent: {
          DEFAULT: "var(--color-accent)",
          hover: "var(--color-accent-hover)",
          foreground: "var(--color-accent-foreground)",
          subtle: "var(--color-accent-subtle)",
          "on-dark": "var(--color-accent-on-dark)",
        },
        status: {
          "pass-bg": "var(--color-status-pass-bg)",
          "pass-fg": "var(--color-status-pass-fg)",
          "pass-solid": "var(--color-status-pass-solid)",
          "fail-bg": "var(--color-status-fail-bg)",
          "fail-fg": "var(--color-status-fail-fg)",
          "fail-solid": "var(--color-status-fail-solid)",
          "fail-border": "var(--color-status-fail-border)",
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
        // Severity + history maps lifted verbatim from the Run Dashboard (index.css).
        severity: {
          "critical-fg": "var(--color-severity-critical-fg)",
          "critical-bg": "var(--color-severity-critical-bg)",
          "critical-dot": "var(--color-severity-critical-dot)",
          "major-fg": "var(--color-severity-major-fg)",
          "major-bg": "var(--color-severity-major-bg)",
          "major-dot": "var(--color-severity-major-dot)",
          "minor-fg": "var(--color-severity-minor-fg)",
          "minor-bg": "var(--color-severity-minor-bg)",
          "minor-dot": "var(--color-severity-minor-dot)",
        },
        history: {
          "new-fg": "var(--color-history-new-fg)",
          "new-bg": "var(--color-history-new-bg)",
          "regression-fg": "var(--color-history-regression-fg)",
          "regression-bg": "var(--color-history-regression-bg)",
          "known-fg": "var(--color-history-known-fg)",
          "known-bg": "var(--color-history-known-bg)",
          "flaky-fg": "var(--color-history-flaky-fg)",
          "flaky-bg": "var(--color-history-flaky-bg)",
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
      boxShadow: {
        // One soft, single-elevation card lift (no glow, no heavy drop). Cards
        // read as lifted rather than as flat outlines. Used app-wide via
        // `shadow-card` so the elevation stays consistent.
        card: "0 1px 3px rgba(0,0,0,0.06), 0 4px 12px rgba(0,0,0,0.04)",
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
