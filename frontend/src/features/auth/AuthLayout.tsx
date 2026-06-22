import {
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";

import { Link } from "@/components/Link";
import { Wordmark } from "@/components/Wordmark";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The auth shell — faithful to "Polaris UI/Polaris Auth.dc.html": a split screen
 * with a brand / product panel on the left (hidden below 900px) and a fixed
 * 520px form panel on the right. The product panel shows a sample finding and
 * the trust-mark legend — the brand's one signature — so the front door sells the
 * thing the app is about. Sign in / sign up are wired to B2; this is presentation.
 */
export function AuthLayout({
  title,
  titleText,
  subtitle,
  children,
  footer,
}: {
  title: ReactNode;
  /** Plain-text title for the heading's accessible name (when `title` is styled,
   *  e.g. the indigo "i", so AT reads "Polaris" not "Polar i s"). */
  titleText?: string;
  subtitle: ReactNode;
  /** The form (fields + submit). */
  children: ReactNode;
  /** The switch-screen line under the form (e.g. "New to Polaris? Create account"). */
  footer?: ReactNode;
}) {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-surface text-foreground">
      <BrandPanel />

      <div className="flex w-full flex-col min-[900px]:w-[520px] min-[900px]:flex-none">
        {/* Header — the wordmark shows here only below 900px (the brand panel hides). */}
        <header className="flex h-16 flex-none items-center px-6 min-[900px]:px-14">
          <Link to="/" aria-label="Polaris — home" className="flex min-[900px]:hidden">
            <Wordmark className="text-[19px]" />
          </Link>
        </header>

        <main className="flex flex-1 flex-col overflow-y-auto px-6 py-6 min-[900px]:px-14">
          <div className="m-auto w-full max-w-[368px]">
            <h1
              aria-label={titleText}
              className="text-[23px] font-semibold tracking-[-0.015em] text-foreground"
            >
              {title}
            </h1>
            <p className="mt-1.5 text-[13.5px] text-muted-foreground">{subtitle}</p>
            <div className="mt-[26px]">{children}</div>
            {footer ? (
              <p className="mt-6 text-center text-[13px] text-muted-foreground">
                {footer}
              </p>
            ) : null}
          </div>
        </main>

        <footer className="flex flex-none items-center justify-between border-t border-status-neutral-bg px-6 py-4 text-xs text-status-neutral-solid min-[900px]:px-14">
          <span>Protected by SSO · SAML</span>
          <span>
            Need help? <span className="text-muted-foreground">Contact</span>
          </span>
        </footer>
      </div>
    </div>
  );
}

// ---- brand / product panel (static) ----------------------------------------

function BrandPanel() {
  return (
    <aside className="hidden flex-1 flex-col border-r border-border bg-background px-14 py-10 min-[900px]:flex">
      <Wordmark className="text-[30px] tracking-[-0.025em]" />

      <div className="flex max-w-[440px] flex-1 flex-col justify-center pt-[72px]">
        <h2 className="text-[30px] font-semibold leading-[1.2] tracking-[-0.025em] text-foreground">
          Tests you can trust.
        </h2>
        <p className="mt-3.5 max-w-[400px] text-[14.5px] leading-[1.6] text-muted-foreground">
          Polaris reads your codebase, generates and runs tests, and reports ranked
          findings — each with a mark telling you how much to believe it.
        </p>

        <FindingPreview />
        <TrustLegend />
      </div>

      <div className="text-xs text-status-neutral-solid">
        Autonomous QA · SOC 2 Type II · © 2026 Polaris
      </div>
    </aside>
  );
}

function FindingPreview() {
  return (
    <div className="mb-[26px] mt-[30px] max-w-[400px] rounded-xl border border-border bg-surface px-[18px] py-4">
      <div className="mb-[11px] flex items-center justify-between">
        <span className="rounded-[5px] bg-status-neutral-bg px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
          run #482 · API
        </span>
        <span className="rounded-[5px] bg-status-fail-bg px-2 py-0.5 text-[10.5px] font-semibold tracking-[0.02em] text-status-fail-solid">
          Critical
        </span>
      </div>
      <div className="mb-3 text-[15px] font-semibold leading-[1.35] tracking-[-0.01em] text-foreground">
        Orders accepted without authentication
      </div>
      <div className="flex items-center gap-[9px]">
        <span className="inline-flex items-center gap-1.5 rounded-md border border-trust-rule-border bg-trust-rule-bg px-[9px] py-[3px] font-mono text-[11px] text-trust-rule-fg">
          <span
            className="h-[9px] w-[9px] rounded-full bg-trust-rule-solid"
            aria-hidden="true"
          />
          rule-derived
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-status-info-fg">
          <span
            className="h-[5px] w-[5px] rounded-full bg-status-info-fg"
            aria-hidden="true"
          />
          New
        </span>
      </div>
    </div>
  );
}

function TrustLegend() {
  return (
    <>
      <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-status-neutral-solid">
        The trust mark
      </div>
      <div className="mt-3 flex flex-col gap-2.5">
        <LegendRow
          glyph={
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full bg-trust-rule-solid"
              aria-hidden="true"
            />
          }
          term="rule-derived"
          description="the assertion follows from a real rule"
        />
        <LegendRow
          glyph={
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full border-2 border-trust-char-solid bg-surface"
              aria-hidden="true"
            />
          }
          term="characterization"
          description="it pins current behavior"
        />
        <LegendRow
          glyph={
            <span
              className="flex h-2.5 w-2.5 shrink-0 items-center justify-center rounded-full border-2 border-trust-spec-solid"
              aria-hidden="true"
            >
              <span className="h-[3px] w-[3px] rounded-full bg-trust-spec-solid" />
            </span>
          }
          term="spec-grounded"
          description="anchored to a documented contract"
        />
      </div>
    </>
  );
}

function LegendRow({
  glyph,
  term,
  description,
}: {
  glyph: ReactNode;
  term: string;
  description: string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      {glyph}
      <span className="text-[12.5px] text-foreground-secondary">
        <span className="font-semibold">{term}</span> — {description}
      </span>
    </div>
  );
}

// ---- shared form controls --------------------------------------------------

/** A labelled field matching the auth design (h-42, 9px radius, indigo focus). */
export function AuthField({
  id,
  label,
  labelAccessory,
  className,
  ...props
}: {
  id: string;
  label: string;
  /** Optional element on the right of the label row (e.g. "Forgot password?"). */
  labelAccessory?: ReactNode;
} & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <div className="mb-[7px] flex items-center justify-between gap-2">
        <label
          htmlFor={id}
          className="text-[13px] font-medium text-foreground-secondary"
        >
          {label}
        </label>
        {labelAccessory}
      </div>
      <input
        id={id}
        className={cn(
          "h-[42px] w-full rounded-[9px] border border-border bg-surface px-[13px] text-sm text-foreground placeholder:text-status-neutral-solid",
          "focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-background",
          className,
        )}
        {...props}
      />
    </div>
  );
}

/** The full-width primary submit button (h-44, 9px radius). */
export function AuthSubmit({
  children,
  ...props
}: { children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <Button
      type="submit"
      className="h-[44px] w-full rounded-[9px] text-sm font-semibold"
      {...props}
    >
      {children}
    </Button>
  );
}

/**
 * The "Continue with SSO" button from the design. There's no SSO backend yet, so
 * it stays honest: clicking explains it isn't available and points at the email
 * form below, rather than pretending to start a flow.
 */
export function SsoButton({ label }: { label: string }) {
  const [noted, setNoted] = useState(false);
  return (
    <div>
      <Button
        type="button"
        variant="outline"
        onClick={() => setNoted(true)}
        className="h-[44px] w-full gap-[9px] rounded-[9px] text-[13.5px] font-medium text-foreground-secondary"
      >
        <span
          className="h-[15px] w-[15px] rounded-[4px] border-[1.5px] border-status-neutral-solid"
          aria-hidden="true"
        />
        {label}
      </Button>
      {noted ? (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          Single sign-on isn&rsquo;t available yet — continue with your email and
          password below.
        </p>
      ) : null}
    </div>
  );
}

/** The "or" divider between SSO and the email form. */
export function AuthDivider() {
  return (
    <div className="flex items-center gap-3">
      <span className="h-px flex-1 bg-border" />
      <span className="text-[11.5px] text-status-neutral-solid">or</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
