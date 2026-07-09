import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Drawer } from "@/components/Drawer";

/** A right-side detail drawer for the admin console — the shared Drawer (focus-trapped,
 *  Esc-to-close, floats above the page so it never adds a page scroll, ADR-0066) with a
 *  sticky close affordance and consistent padding. */
export function AdminDetailDrawer({
  open,
  onClose,
  label,
  children,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
}) {
  return (
    <Drawer open={open} onClose={onClose} label={label}>
      <div className="flex items-center justify-between border-b border-border-subtle px-5 py-3.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-marker">
          Details
        </span>
        <button
          type="button"
          aria-label="Close"
          data-autofocus
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-md text-status-neutral-solid transition-colors hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
    </Drawer>
  );
}
