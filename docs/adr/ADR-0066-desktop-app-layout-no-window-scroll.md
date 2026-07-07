# ADR-0066 — Desktop-app layout: the window never scrolls

## Status

Accepted.

## Context

The app read like a website: the whole page scrolled under a scrollbar on the browser
window, and the fixed chrome (sidebar, top bar) was the only thing that stayed put by
accident of `overflow: hidden` on the shell root. On tall views the entire content
column scrolled as one block — headers, filters, and toolbars scrolled away with the
content. The product should feel like a **desktop application**: a fixed frame, with
scroll living inside the region that actually overflows (a page body, a table, a list),
never on the whole page.

## Decision

**The window/page never scrolls. Scroll is always contained in a bounded region.**

1. **A fixed height chain (global CSS).** `html`, `body`, and `#root` are pinned to
   `100dvh` and `overflow: hidden`. `dvh` (dynamic viewport height) — not `vh` — tracks
   the real viewport so mobile browser chrome can't create a phantom page scrollbar.
   Every view therefore mounts into a bounded viewport and can only scroll *inside*
   itself.

2. **The app shell is a fixed frame.** The sidebar + top bar never move; the content
   region is `min-h-0 flex-1` and keeps an `overflow-y-auto` **safety net** only — a
   view that isn't height-managed degrades to a contained scroll here rather than
   clipping. In practice it should never show, because…

3. **Every view is full-height and owns its scroll.** A reusable `PageShell`
   (`flex h-full min-h-0 flex-col`) gives a **non-scrolling header slot** (title +
   toolbar/filters stay put) above a single **scrollable body** (`min-h-0 flex-1
   overflow-y-auto`). Pages with their own header component use the same
   `flex h-full min-h-0 flex-col` + scrolling `<main>` shape. Standalone views (auth,
   error, splash, public status) each fill `#root` and scroll their own body.

4. **Overflow inside a body is handled at the section.** Where a single region is the
   overflow (a long table/list), it scrolls internally or paginates — the existing
   findings inbox and run dashboard already do this (two-pane, internally scrolled), and
   new list pages keep their pagination.

The load-bearing rule: `min-h-0` on every flex ancestor of a scroll region, so a flex
child is allowed to shrink below its content and hand the overflow to the inner
`overflow-y-auto` — without it, flexbox refuses to shrink and the scroll escapes upward
to the window.

## Consequences

- The chrome (sidebar, top bar) and each page's header/filters stay fixed while content
  scrolls beneath them — the app reads like desktop software, not a web page. There is
  no window scrollbar anywhere, on any route.
- One consistent frame (`PageShell`) means new pages get the behaviour for free and
  can't reintroduce a page scroll; `min-h-0` is the one thing a new scroll region must
  remember.
- `100dvh` avoids the classic mobile `100vh` overshoot; the trade-off is that a view
  which genuinely needs more than the viewport must provide an internal scroll region
  (it can't lean on the window) — which is exactly the desired discipline.
- Extremely short viewports still work: the page body (or the auth/error body) scrolls
  internally, so nothing is ever clipped out of reach.
