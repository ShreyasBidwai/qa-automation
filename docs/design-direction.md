# QA Platform — UI Design Direction

## North star
A light, professional B2B SaaS product UI. It should feel at home next to Stripe's
dashboard, Linear, Sentry, and Vercel — quiet, dense, data-forward, trustworthy. Not a
marketing site, not a dark "developer-tool" theme, not sci-fi, no AI-assistant chrome,
no decorative gradients. The craft is in restraint and precision, not flourish.

## References (what we emulate, and why)
- **Stripe Dashboard** — light, dense, professional data UI; one accent doing the work.
- **Linear** — spacing discipline, rationed accent, quiet monochrome, border-not-fill
  elevation, instrument-panel density. We take its craft in LIGHT mode.
- **Sentry** — our domain analog (findings/triage): strong information hierarchy +
  progressive disclosure (collapsible sections, detail in a drawer). Its known weakness is
  dashboard noise from bad grouping — our grouping/confidence is the antidote; foreground it.
- **Vercel** — clean, restrained, content-first.

## Color — light, rationed
Grays are the workhorse; ONE accent (indigo) for primary action / active only; semantic
colors strictly for meaning, never decoration. (Tailwind zinc + indigo + semantics — keeps
it consistent with the existing Sprint 0 tokens.)
- Canvas/page: zinc-50 `#FAFAFA`. Cards/surfaces: white `#FFFFFF`.
- Borders: hairline zinc-200 `#E4E4E7`; hover zinc-300.
- Text: primary zinc-900 `#18181B`, secondary zinc-500 `#71717A`, muted zinc-400.
- Accent (indigo — one primary action per view, active nav, focus): indigo-600 `#4F46E5`.
- Semantic (meaning only):
  - critical / error: red-600 `#DC2626` on red-50 `#FEF2F2`
  - major / warning: amber-600 `#D97706` on amber-50 `#FFFBEB`
  - pass / healthy / rule-derived: emerald-600 `#059669` on emerald-50 `#ECFDF5`
  - new / info: blue-600 `#2563EB` on blue-50 `#EFF6FF`
- Elevation: 3–4 steps max (canvas → card → popover → modal) via 1px borders + soft
  shadows, NOT heavy fills.

## Typography
- UI: **Inter** (variable) — the industry-standard professional sans. Weights 400 / 500
  only (avoid 600+ in product chrome).
- Code / paths / IDs / endpoints / SQL: a mono — **JetBrains Mono** or `ui-monospace`.
- Scale (sentence case ALWAYS; ALL-CAPS only for tiny eyebrow labels with +tracking):
  - page title 20–22px / 500, tight tracking (~−0.01em)
  - section 16–18px / 500
  - body 14px / 400, line-height 1.5
  - meta/caption 12–13px, zinc-500
- Tight (slightly negative) tracking on titles; never cramped — text never against edges
  (≥16–24px padding).

## Spacing & grid
- 8px scale (4 / 8 / 12 / 16 / 24 / 32 / 48); 4px half-step for fine work. Line-heights on
  the 4px grid.
- Dense but breathing: data-forward (this is a technical tool), not cramped. Card padding
  16–20px.

## Layout patterns
- **App shell**: quiet left sidebar nav (Projects, Runs) + top bar (context, the one
  primary action, filters). Persistent.
- **Lists**: dense tables/rows, scannable, sortable/filterable from the header (Linear-style
  display options).
- **Detail**: progressive disclosure — open a finding into a right-side drawer or split
  view; group workflow actions apart from details; collapsible sections (Sentry's lesson).
  Never dump everything at once.
- The findings list shows **findings** (grouped, ranked), never raw test rows — the
  grouping / confidence / severity must read at a glance.

## Components (shadcn/Radix + Tailwind — already the stack)
- Buttons: exactly one primary (indigo, filled) per view; everything else secondary
  (zinc border) or ghost. Active = scale(0.98).
- Badges/pills: quiet, small (11–12px), semantic background + same-family dark text
  (red-50 bg / red-700 text). Confidence (rule-derived green / behaviour-changed amber),
  severity (critical/major/minor), status (new/regression/flaky/known) — legible, calm.
- Tables: no zebra; hairline row borders; hover highlight; generous row height (44–48px);
  monospace for code-ish cells (endpoints, paths).
- Empty/error states: direction, not mood — say what to do next ("No runs yet. Register a
  project to start."), in the product's voice. Errors state what happened + how to fix;
  never apologize, never vague.

## Quality floor (non-negotiable)
- Responsive down to a usable tablet/narrow width.
- Visible keyboard focus rings (indigo, 2px) on every interactive element.
- Respect `prefers-reduced-motion`. Motion is functional (state changes, drawer slide),
  never ambient/decorative.
- WCAG AA contrast on all text and badges.

## Hard NOs (the anti-AI-fluff list)
- No dark mode for v1 (light only; dark can come later via the same token system).
- No neon, glow, sci-fi, glassmorphism, or decorative gradients.
- No "✨ AI" sparkle chrome, assistant-bubble decoration, or robot/brain mascots.
- No more than the one indigo accent; semantic colors only where they mean something.
- No Title Case, no ALL-CAPS body, no emoji in product chrome.
- No heavy drop shadows or filled-color cards for elevation — borders + soft shadow only.
- No icon zoo — one consistent set (Lucide), outline, used sparingly.

## Voice (copy is design material)
Write from the user's side: "Register a project", "Run tests", "View findings" — name what
they control, plain verbs, sentence case, active voice. An action keeps its name through the
flow (button "Run" → toast "Run started").
