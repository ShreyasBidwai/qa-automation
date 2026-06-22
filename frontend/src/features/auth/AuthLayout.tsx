import type { InputHTMLAttributes, ReactNode } from "react";

import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import { Input } from "@/components/ui/input";

/**
 * The auth shell (design brief screen 0). A calm, centered front door — large
 * wordmark, one card, generous whitespace. These screens are STATIC PLACEHOLDERS:
 * Polaris has no auth backend yet (Tier 2), so nothing submits. Every page makes
 * that honest with a visible preview note; the forms exist so the product reads
 * as complete and ready to wire up.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Link to="/" aria-label="Polaris — home">
            <Wordmark size="lg" />
          </Link>
          <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-foreground">{title}</h1>
          <div className="mt-5">{children}</div>
        </div>
        {footer ? (
          <p className="mt-5 text-center text-sm text-muted-foreground">{footer}</p>
        ) : null}
        <p className="mx-auto mt-6 max-w-xs text-center text-xs text-muted-foreground">
          Preview only — authentication isn&rsquo;t wired up yet. Sign-in lands in
          Tier&nbsp;2.
        </p>
      </div>
    </div>
  );
}

/** A labelled field for the auth forms. */
export function AuthField({
  id,
  label,
  ...props
}: { id: string; label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
      </label>
      <Input id={id} {...props} />
    </div>
  );
}
