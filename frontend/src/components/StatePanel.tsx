import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A centered state — the shared shape behind empty / error / clean / 404 / 500
 * pages (design brief: states are first-class, invitations not apologies). An
 * optional tone-coloured icon, a title, a plain next-step description, an optional
 * mono detail line (an error code), and actions.
 */
export type StateTone = "neutral" | "danger" | "success";

const TONE: Record<StateTone, string> = {
  neutral: "border border-dashed border-status-neutral-solid text-muted-foreground",
  danger: "bg-status-fail-bg text-status-fail-fg",
  success: "bg-status-pass-bg text-status-pass-fg",
};

export function StatePanel({
  icon: Icon,
  tone = "neutral",
  eyebrow,
  title,
  description,
  code,
  actions,
}: {
  icon?: LucideIcon;
  tone?: StateTone;
  eyebrow?: string;
  title: string;
  description: ReactNode;
  /** A mono detail line, e.g. an error code or id. */
  code?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      {Icon ? (
        <div
          className={cn(
            "mb-5 flex h-12 w-12 items-center justify-center rounded-full",
            TONE[tone],
          )}
        >
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
      ) : null}
      {eyebrow ? (
        <div className="mb-2.5 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {eyebrow}
        </div>
      ) : null}
      <h2 className="text-[17px] font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
        {description}
      </p>
      {code ? (
        <p className="mt-2 font-mono text-[11.5px] text-muted-foreground">{code}</p>
      ) : null}
      {actions ? (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">
          {actions}
        </div>
      ) : null}
    </div>
  );
}
