import type { ReactNode } from "react";

const APP_NAME = import.meta.env.VITE_APP_NAME ?? "QA Automation Platform";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-surface">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-2 px-6">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full bg-accent"
            aria-hidden="true"
          />
          <span className="text-sm font-semibold tracking-tight">{APP_NAME}</span>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
    </div>
  );
}
