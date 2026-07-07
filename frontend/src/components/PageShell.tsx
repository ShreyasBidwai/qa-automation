import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A full-height page frame (ADR-0066): fills the app content region and NEVER lets the
 * window/page scroll — a fixed (non-scrolling) header slot above a single scrollable
 * body. Overflowing content scrolls INSIDE `body` (and callers can nest further
 * per-section scroll/pagination within it), so the shell chrome + page header stay put
 * like a desktop app.
 *
 * `maxWidth` centres the header + body content on the same measure (the pages use
 * `max-w-[1760px]` / narrower for forms); pass `bodyClassName` to tune body padding.
 */
export function PageShell({
  header,
  children,
  maxWidth = "max-w-[1760px]",
  bodyClassName,
}: {
  header?: ReactNode;
  children: ReactNode;
  maxWidth?: string;
  bodyClassName?: string;
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
          "min-h-0 flex-1 overflow-y-auto px-6 py-6 lg:px-8",
          bodyClassName,
        )}
      >
        <div className={cn("mx-auto", maxWidth)}>{children}</div>
      </div>
    </div>
  );
}
