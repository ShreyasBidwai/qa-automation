import type { InputHTMLAttributes, ReactNode } from "react";

import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import { Input } from "@/components/ui/input";

/**
 * The auth shell (design brief screen 0). A calm, centered front door — large
 * wordmark, one card, generous whitespace. Sign in / sign up are wired to the B2
 * session endpoints; an optional `note` carries an honest "not yet" line for the
 * screens (password reset) that aren't wired yet.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
  note,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
  note?: ReactNode;
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
        {note ? (
          <p className="mx-auto mt-6 max-w-xs text-center text-xs text-muted-foreground">
            {note}
          </p>
        ) : null}
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
