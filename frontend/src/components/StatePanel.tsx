import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A centered state — the shared shape behind empty / error / clean / 404 / 500 /
 * detail-unselected (Polaris States.dc.html; the brief: states are first-class,
 * invitations not apologies). A tone-coloured illustration (decorative — the
 * heading carries the meaning for assistive tech), a heading, a plain next-step
 * body, an optional mono detail line (an error code / id), and the actions.
 *
 * Tone sets the illustration: `neutral` is the dashed "invitation" squircle,
 * `danger` / `success` are filled circles with a subtle tone border. Size scales
 * it for where it lives: `sm` a detail panel, `md` an in-shell state, `lg` a
 * full-screen 404 / 500.
 */
export type StateTone = "neutral" | "danger" | "success";
export type StateSize = "sm" | "md" | "lg";

const SIZE: Record<
  StateSize,
  { box: string; radius: string; icon: string; heading: string; body: string }
> = {
  sm: {
    box: "h-11 w-11",
    radius: "rounded-[10px]",
    icon: "h-[18px] w-[18px]",
    heading: "text-[15px]",
    body: "max-w-[260px] text-[13px]",
  },
  md: {
    box: "h-[52px] w-[52px]",
    radius: "rounded-[13px]",
    icon: "h-[22px] w-[22px]",
    heading: "text-[17px]",
    body: "max-w-[360px] text-[13.5px]",
  },
  lg: {
    box: "h-[52px] w-[52px]",
    radius: "rounded-[13px]",
    icon: "h-[22px] w-[22px]",
    heading: "text-[22px] tracking-[-0.015em]",
    body: "max-w-[380px] text-sm",
  },
};

const TONE: Record<StateTone, string> = {
  neutral: "border border-dashed border-marker text-status-neutral-solid",
  danger:
    "rounded-full border border-status-fail-border bg-status-fail-bg text-status-fail-solid",
  success:
    "rounded-full border border-status-pass-border bg-status-pass-bg text-status-pass-solid",
};

export function StatePanel({
  icon: Icon,
  tone = "neutral",
  size = "md",
  eyebrow,
  title,
  description,
  code,
  actions,
}: {
  icon?: LucideIcon;
  tone?: StateTone;
  size?: StateSize;
  eyebrow?: string;
  title: string;
  description: ReactNode;
  /** A mono detail line, e.g. an error code or id. */
  code?: string;
  actions?: ReactNode;
}) {
  const s = SIZE[size];
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {Icon ? (
        <div
          aria-hidden="true"
          className={cn(
            "mb-5 flex items-center justify-center",
            s.box,
            // neutral keeps the size's dashed squircle; danger/success add rounded-full.
            tone === "neutral" ? s.radius : null,
            TONE[tone],
          )}
        >
          <Icon className={s.icon} aria-hidden="true" />
        </div>
      ) : null}
      {eyebrow ? (
        <div className="mb-3.5 font-mono text-[13px] text-status-neutral-solid">
          {eyebrow}
        </div>
      ) : null}
      <h2 className={cn("font-semibold text-foreground", s.heading)}>{title}</h2>
      <p className={cn("mx-auto mt-2 leading-[1.55] text-muted-foreground", s.body)}>
        {description}
      </p>
      {code ? (
        <p className="mt-2 font-mono text-[11.5px] text-status-neutral-solid">{code}</p>
      ) : null}
      {actions ? (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">
          {actions}
        </div>
      ) : null}
    </div>
  );
}
