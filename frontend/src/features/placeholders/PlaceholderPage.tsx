import type { ReactNode } from "react";

import { PageHeader } from "@/components/PageHeader";

/**
 * A first-class placeholder for destinations that exist in the shell now but land
 * in a later slice (the Findings inbox, Account, Settings). Honest, on-brand, and
 * clearly marked as not-yet-built — never a dead link or a fake screen.
 */
export function PlaceholderPage({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <>
      <PageHeader title={title} />
      <main className="flex-1 px-6 py-8">
        <div className="mx-auto max-w-md rounded-xl border border-dashed border-border bg-surface px-6 py-14 text-center">
          <p className="text-sm font-medium text-foreground">Coming in a later slice</p>
          <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted-foreground">
            {description}
          </p>
          {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
        </div>
      </main>
    </>
  );
}
