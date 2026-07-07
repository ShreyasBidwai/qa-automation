import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A full-height page frame (ADR-0066): fills the app content region and NEVER lets the
 * window/page scroll — a fixed (non-scrolling) header slot above the body. The shell
 * chrome + page header always stay put like a desktop app.
 *
 * `scroll` (default true) — the body scrolls as one region. Good for pages that are a
 * single flow. Pass `scroll={false}` to CONTAIN the body to the viewport instead: the
 * body doesn't scroll at all, and the page lays out a `flex h-full min-h-0 flex-col`
 * of children where the OVERFLOWING SECTION (a table/list) scrolls internally or
 * paginates — so there's no tall page-body scrollbar, only per-section ones.
 *
 * `maxWidth` centres the header + body on the same measure; `bodyClassName` tunes body
 * padding.
 */
export function PageShell({
  header,
  children,
  maxWidth = "max-w-[1760px]",
  bodyClassName,
  scroll = true,
}: {
  header?: ReactNode;
  children: ReactNode;
  maxWidth?: string;
  bodyClassName?: string;
  scroll?: boolean;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {header ? (
        <div className="shrink-0 border-b border-border-subtle px-6 pb-4 pt-6 lg:px-8">
          <div className={cn("mx-auto", maxWidth)}>{header}</div>
        </div>
      ) : null}
      <div
        className={cn(
          "min-h-0 flex-1 px-6 py-6 lg:px-8",
          scroll ? "overflow-y-auto" : "overflow-hidden",
          bodyClassName,
        )}
      >
        <div
          className={cn(
            "mx-auto",
            maxWidth,
            scroll ? undefined : "flex h-full min-h-0 flex-col",
          )}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
