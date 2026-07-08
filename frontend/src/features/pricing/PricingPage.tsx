import {
  AlertTriangle,
  Boxes,
  Check,
  Clock,
  CreditCard,
  Tags,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { PageShell } from "@/components/PageShell";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { planApi } from "@/lib/api/client";
import type { PlanItem } from "@/lib/api/types";

/**
 * Plans & pricing (B5, ADR-0069) — the customer-facing tier comparison. One card per
 * public plan from GET /plans: the per-seat price (or "Custom" when null), the metered
 * run-credit allowance, the quotas (projects / seats / parallelism / retention), and the
 * plan's feature flags as bullets. A NULL quota renders "Unlimited"; a NULL price reads
 * "Custom" with a "contact us" nudge — we never invent a number the catalog didn't give.
 */
export function PricingPage() {
  const [plans, setPlans] = useState<PlanItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void planApi.list().then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setPlans(result.data.items);
        setError(null);
      } else {
        setPlans(null);
        setError(result.error ?? "Couldn't load the plans.");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <PageShell
      header={
        <div className="flex items-center gap-3">
          <span className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-marker">
            <CreditCard
              className="h-4 w-4 text-status-neutral-solid"
              aria-hidden="true"
            />
          </span>
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
              Plans &amp; pricing
            </h1>
            <p className="mt-0.5 text-[13px] text-status-neutral-solid">
              Seats for the team, run-credits for the agentic work
            </p>
          </div>
        </div>
      }
    >
      {loading ? (
        <PricingSkeleton />
      ) : error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load the plans"
          description="This is usually temporary — the catalog service may be briefly unavailable."
          code={error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : !plans || plans.length === 0 ? (
        <StatePanel
          icon={Tags}
          title="No plans published yet"
          description="The plan catalog is empty right now. Check back soon, or reach out to talk through what you need."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 min-[1180px]:grid-cols-4">
          {plans.map((plan) => (
            <PlanCard key={plan.key} plan={plan} />
          ))}
        </div>
      )}
    </PageShell>
  );
}

// ---- one plan card ----------------------------------------------------------

function PlanCard({ plan }: { plan: PlanItem }) {
  const custom = plan.price_per_seat_monthly_usd === null;
  return (
    <div className="flex flex-col rounded-xl border border-border bg-surface p-5 shadow-card">
      <h2 className="text-[15px] font-semibold text-foreground">{plan.name}</h2>

      {/* Price — a real per-seat number, or an honest "Custom" for a null price. */}
      <div className="mt-3 flex items-baseline gap-1.5">
        {custom ? (
          <span className="text-[26px] font-semibold leading-none tracking-[-0.02em] text-foreground">
            Custom
          </span>
        ) : (
          <>
            <span className="text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground">
              {formatUsd(plan.price_per_seat_monthly_usd as number)}
            </span>
            <span className="text-[13px] text-muted-foreground">/seat/mo</span>
          </>
        )}
      </div>
      <p className="mt-1.5 text-[12.5px] text-status-neutral-solid">
        {custom ? "Contact us for pricing" : "billed per seat, monthly"}
      </p>

      {/* Run-credits — the metered unit; null = unlimited. */}
      <div className="mt-4 rounded-lg border border-border-subtle bg-background px-3.5 py-3">
        <div className="text-[11px] font-medium text-muted-foreground">
          Run credits / month
        </div>
        <div className="mt-1 text-lg font-semibold tabular-nums text-foreground">
          {quota(plan.included_run_credits_monthly)}
        </div>
      </div>

      {/* Quotas — each an icon + label + value; null renders "Unlimited". */}
      <dl className="mt-4 space-y-2.5">
        <QuotaRow icon={Boxes} label="Projects" value={quota(plan.max_projects)} />
        <QuotaRow icon={Users} label="Seats" value={quota(plan.max_seats)} />
        <QuotaRow
          icon={Zap}
          label="Parallel runs"
          value={String(plan.max_parallelism)}
        />
        <QuotaRow
          icon={Clock}
          label="History retention"
          value={`${plan.retention_days} days`}
        />
      </dl>

      {/* Feature flags — only the enabled ones, humanized into bullets. */}
      <FeatureList features={plan.features} />
    </div>
  );
}

function QuotaRow({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5 text-status-neutral-solid" aria-hidden="true" />
        {label}
      </dt>
      <dd className="text-[13px] font-medium tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

function FeatureList({ features }: { features: Record<string, unknown> }) {
  const enabled = featureLabels(features);
  if (enabled.length === 0) return null;
  return (
    <ul className="mt-4 space-y-1.5 border-t border-border-subtle pt-4">
      {enabled.map((label) => (
        <li key={label} className="flex items-start gap-2 text-[13px] text-foreground">
          <Check
            className="mt-0.5 h-3.5 w-3.5 flex-none text-status-pass-solid"
            aria-hidden="true"
          />
          {label}
        </li>
      ))}
    </ul>
  );
}

// ---- helpers ----------------------------------------------------------------

/** A null quota means "no cap" (ADR-0069) — render it as such, never a bare "null". */
function quota(value: number | null): string {
  return value === null ? "Unlimited" : value.toLocaleString();
}

/** Whole-dollar USD (plans are priced in round dollars); no cents to keep it clean. */
function formatUsd(amount: number): string {
  return `$${Math.round(amount).toLocaleString()}`;
}

/**
 * Humanize the `features` flag bag into display labels, keeping only the enabled ones.
 * A boolean `true` shows the humanized key; a truthy string/number shows "Key: value";
 * anything falsy is dropped — so a card lists only what the tier actually includes.
 */
function featureLabels(features: Record<string, unknown>): string[] {
  const labels: string[] = [];
  for (const [key, value] of Object.entries(features)) {
    if (value === true) {
      labels.push(humanize(key));
    } else if (typeof value === "string" && value.trim()) {
      labels.push(`${humanize(key)}: ${value}`);
    } else if (typeof value === "number" && value > 0) {
      labels.push(`${humanize(key)}: ${value.toLocaleString()}`);
    }
  }
  return labels;
}

/** `priority_support` / `sso` → "Priority support" / "SSO" — snake case to a label,
 *  with a few well-known acronyms kept upper-case. */
function humanize(key: string): string {
  const acronyms = new Set(["sso", "saml", "api", "scim"]);
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word, index) =>
      acronyms.has(word.toLowerCase())
        ? word.toUpperCase()
        : index === 0
          ? word.charAt(0).toUpperCase() + word.slice(1)
          : word,
    )
    .join(" ");
}

function PricingSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 min-[1180px]:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-[420px] rounded-xl" />
      ))}
    </div>
  );
}
