import type { ReactNode } from "react";

/**
 * The top bar of a view: context (title + optional eyebrow/description) on the
 * left, the single primary action on the right (design-direction.md — exactly
 * one primary action per view). Sticky so it stays as content scrolls.
 */
export function PageHeader({
  title,
  eyebrow,
  description,
  action,
}: {
  title: string;
  eyebrow?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-surface/95 backdrop-blur">
      <div className="flex min-h-14 items-center justify-between gap-4 px-6 py-3">
        <div className="min-w-0">
          {eyebrow ? (
            <div className="text-xs text-muted-foreground">{eyebrow}</div>
          ) : null}
          <h1 className="truncate text-[20px] font-medium tracking-tight text-foreground">
            {title}
          </h1>
          {description ? (
            <p className="mt-0.5 truncate text-sm text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </header>
  );
}
