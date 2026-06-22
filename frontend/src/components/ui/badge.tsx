import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

// Status colours come from centralized tokens (tailwind.config.js → CSS vars).
// Each level pairs a light background with a readable foreground; colour is
// never the sole signal — callers add an icon and a text label.
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      level: {
        pass: "bg-status-pass-bg text-status-pass-fg",
        fail: "bg-status-fail-bg text-status-fail-fg",
        flaky: "bg-status-flaky-bg text-status-flaky-fg",
        info: "bg-status-info-bg text-status-info-fg",
        neutral: "bg-status-neutral-bg text-status-neutral-fg",
      },
    },
    defaultVariants: { level: "neutral" },
  },
);

export type BadgeProps = HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>;

export function Badge({ className, level, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ level }), className)} {...props} />;
}
