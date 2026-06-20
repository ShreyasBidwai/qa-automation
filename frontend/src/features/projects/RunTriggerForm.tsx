import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { runApi } from "@/lib/api/client";
import type { RunCreateBody, SelectionStrategy } from "@/lib/api/types";
import { navigate } from "@/lib/router";

type Mode = "mode_b" | "mode_c";

/** Trigger a run: Mode B (full sweep / change impact) or Mode C (a prompt). */
export function RunTriggerForm({ projectId }: { projectId: string }) {
  const [mode, setMode] = useState<Mode>("mode_b");
  const [strategy, setStrategy] = useState<SelectionStrategy>("full_sweep");
  const [changeset, setChangeset] = useState("");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function buildBody(): RunCreateBody | null {
    if (mode === "mode_c") {
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
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="mode">Mode</Label>
        <Select
          id="mode"
          value={mode}
          onChange={(event) => setMode(event.target.value as Mode)}
        >
          <option value="mode_b">Mode B — autonomous</option>
          <option value="mode_c">Mode C — from a prompt</option>
        </Select>
      </div>

      {mode === "mode_b" ? (
        <div className="space-y-1.5">
          <Label htmlFor="strategy">Selection</Label>
          <Select
            id="strategy"
            value={strategy}
            onChange={(event) => setStrategy(event.target.value as SelectionStrategy)}
          >
            <option value="full_sweep">Full sweep — every testable target</option>
            <option value="change_impact">Change impact — only affected tests</option>
          </Select>
        </div>
      ) : null}

      {mode === "mode_b" && strategy === "change_impact" ? (
        <div className="space-y-1.5">
          <Label htmlFor="changeset">Changed files</Label>
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

      {mode === "mode_c" ? (
        <div className="space-y-1.5">
          <Label htmlFor="prompt">What to test</Label>
          <Textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Check that a guest can add an item to the cart and reach checkout."
          />
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-status-fail-fg">
          {error}
        </p>
      ) : null}

      <Button type="submit" disabled={submitting}>
        {submitting ? "Starting…" : "Run tests"}
      </Button>
    </form>
  );
}
