# ADR-0069 — Real light/dark theming, via the existing CSS-variable tokens

## Status

Accepted.

## Context

Dark mode didn't exist. The only trace of it was `--color-accent-on-dark`, a single
token for the reversed wordmark on an always-dark chip — not a theme, just one
element anticipating a dark surface. Every colour in the app already resolves through
a `--color-*` CSS variable defined once in `index.css` and consumed via the Tailwind
theme (`tailwind.config.js`) — components reference semantic class names
(`bg-surface`, `text-foreground`, …), never raw hex. That discipline is what makes a
real theme cheap: the tokens are already the single seam color lives behind.

## Decision

**Flip the tokens, not the components.** A parallel `:root[data-theme="dark"]` block
in `index.css` redefines every `--color-*` variable already defined on `:root`
(surfaces, accent, the five status families, the oracle-trust marks, severity,
history) to a dark-appropriate value from the *same* hue family, one step down the
relative-contrast ladder (a `bg` token moves from Tailwind's `-50` to `-950`, `fg`
from `-700` to `-400`, `solid` from `-600` to `-500`, `border` from `-200`/`-300` to
`-800`). No component changes: not one `dark:` utility class is added anywhere — the
existing semantic class names automatically repaint because the variable underneath
them changed. The one non-colour casualty is `shadow-card` (a static box-shadow in
`tailwind.config.js`): a black drop-shadow is invisible against a near-black surface,
so `index.css` adds one `[data-theme="dark"] .shadow-card` override (a faint light
ring + a deeper shadow) — still token-adjacent, not a per-component `dark:` sprinkle.

- **`ThemeProvider`/`useTheme`** (`lib/theme/`, split into a context+hook file and a
  provider file — the same shape as `useAuth`/`AuthContext`, for the same reason:
  co-locating a component export with a hook export trips the
  `react-refresh/only-export-components` lint rule). State is `"light" | "dark"`,
  initialized from `localStorage["polaris:theme"]` if the user has chosen explicitly,
  else `prefers-color-scheme`. `setTheme`/`toggleTheme` persist the choice and flip
  `data-theme` on `<html>`.
- **No flash of the wrong theme.** An inline script in `index.html` — same storage
  key, same fallback logic — sets `data-theme` on `<html>` synchronously before any
  stylesheet paints, so a dark-mode user never sees a light flash while React boots.
  `ThemeProvider` takes over from there for the toggle and persistence; it doesn't
  need to (and doesn't) re-run that first paint's logic.
- **The toggle lives in two places**, both real, not redundant by accident: the top
  bar (always in reach, one click, mission item 4) and the Settings page (the fuller,
  labeled control, mission item 5) — both just call the same `useTheme().toggleTheme`.

## Consequences

- Every existing surface reads correctly in dark mode for free — the token discipline
  already in place did the work before this ADR existed. The only thing that needed a
  human eye was picking the dark-mode hex for each token, not touching ~150 component
  call sites.
- A future new status colour/token still only needs ONE addition per theme (the
  light value on `:root`, the dark value on `:root[data-theme="dark"]`) — the
  component that uses it never needs to know a theme exists.
- The tradeoff is that this ADR's dark palette is a mechanical, consistent shade-shift
  (same hue, same relative contrast ladder) rather than a bespoke hand-tuned dark
  palette — a reasonable default; a future design pass can retune specific tokens
  without touching the architecture.
