import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { runApi } from "@/lib/api/client";
import type { RunCreateBody, SelectionStrategy } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

type Mode = "describe" | "autonomous";

const EXAMPLES = [
  "checkout rejects expired cards",
  "orders require authentication",
  "password reset link expires",
];

/** Start a run (#4): describe it (Mode C) or run autonomously (Mode B). */
export function RunTriggerForm({ projectId }: { projectId: string }) {
  const [mode, setMode] = useState<Mode>("describe");
  const [prompt, setPrompt] = useState("");
  const [strategy, setStrategy] = useState<SelectionStrategy>("full_sweep");
  const [changeset, setChangeset] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function buildBody(): RunCreateBody | null {
    if (mode === "describe") {
      if (!prompt.trim()) {
        setError("Describe what to test.");
        return null;
      }
      return { mode: "mode_c", prompt: prompt.trim() };
    }
    if (strategy === "change_impact") {
      const paths = changeset
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (paths.length === 0) {
        setError("List at least one changed file for change-impact selection.");
        return null;
      }
      return { mode: "mode_b", strategy, changeset: paths };
    }
    return { mode: "mode_b", strategy };
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const body = buildBody();
    if (!body) return;

    setSubmitting(true);
    const result = await runApi.create(projectId, body);
    setSubmitting(false);

    if (result.ok && result.data) {
      navigate(`/runs/${result.data.run_id}`);
      return;
    }
    setError(result.error ?? "Could not start the run.");
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-6">
      <div
        role="radiogroup"
        aria-label="How to choose tests"
        className="grid gap-3 sm:grid-cols-2"
      >
        <ModeCard
          selected={mode === "describe"}
          onSelect={() => setMode("describe")}
          title="Describe it"
          description="Say what to test in plain English. Polaris turns it into tests."
        />
        <ModeCard
          selected={mode === "autonomous"}
          onSelect={() => setMode("autonomous")}
          title="Autonomous"
          description="Let Polaris decide — sweep everything, or just what changed."
        />
      </div>

      {mode === "describe" ? (
        <div className="space-y-2">
          <label htmlFor="prompt" className="text-sm font-medium text-foreground">
            What to test
          </label>
          <Textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Describe what to test…"
            rows={3}
          />
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setPrompt(example)}
                className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted-foreground hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <fieldset className="space-y-3">
          <legend className="mb-1 text-sm font-medium text-foreground">Scope</legend>
          <StrategyOption
            value="full_sweep"
            selected={strategy === "full_sweep"}
            onSelect={() => setStrategy("full_sweep")}
            title="Test everything"
            description="A full sweep across every testable target."
          />
          <StrategyOption
            value="change_impact"
            selected={strategy === "change_impact"}
            onSelect={() => setStrategy("change_impact")}
            title="Test only what changed"
            description="Change-impact selection from a list of changed files."
          />
          {strategy === "change_impact" ? (
            <div className="space-y-1.5 pl-1">
              <label
                htmlFor="changeset"
                className="text-sm font-medium text-foreground"
              >
                Changed files
              </label>
              <Textarea
                id="changeset"
                value={changeset}
                onChange={(event) => setChangeset(event.target.value)}
                placeholder={
                  "app/Http/Controllers/CheckoutController.php\napp/Models/Order.php"
                }
                className="font-mono text-[13px]"
              />
              <p className="text-xs text-muted-foreground">One path per line.</p>
            </div>
          ) : null}
        </fieldset>
      )}

      {error ? (
        <p role="alert" className="text-sm text-status-fail-fg">
          {error}
        </p>
      ) : null}

      <Button type="submit" disabled={submitting}>
        {submitting ? "Starting…" : "Start run"}
      </Button>
    </form>
  );
}

function ModeCard({
  selected,
  onSelect,
  title,
  description,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  description: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "rounded-xl border p-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        selected
          ? "border-accent bg-accent-subtle"
          : "border-border bg-surface hover:bg-background",
      )}
    >
      <div
        className={cn(
          "text-sm font-medium",
          selected ? "text-accent" : "text-foreground",
        )}
      >
        {title}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
    </button>
  );
}

function StrategyOption({
  value,
  selected,
  onSelect,
  title,
  description,
}: {
  value: string;
  selected: boolean;
  onSelect: () => void;
  title: string;
  description: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border p-3",
        selected ? "border-accent bg-accent-subtle" : "border-border bg-surface",
      )}
    >
      <input
        type="radio"
        name="strategy"
        value={value}
        checked={selected}
        onChange={onSelect}
        className="mt-0.5 h-4 w-4 text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <span>
        <span className="block text-sm font-medium text-foreground">{title}</span>
        <span className="block text-xs text-muted-foreground">{description}</span>
      </span>
    </label>
  );
}
