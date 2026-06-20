import type { AnchorHTMLAttributes, ReactNode } from "react";

import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  to: string;
  children: ReactNode;
};

/** An accessible in-app link: a real <a> that routes without a full reload. */
export function Link({ to, className, children, onClick, ...props }: LinkProps) {
  return (
    <a
      href={to}
      className={cn(
        "rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
      onClick={(event) => {
        onClick?.(event);
        // Let modified clicks (new tab) and non-primary buttons behave natively.
        if (
          event.defaultPrevented ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.button !== 0
        ) {
          return;
        }
        event.preventDefault();
        navigate(to);
      }}
      {...props}
    >
      {children}
    </a>
  );
}
