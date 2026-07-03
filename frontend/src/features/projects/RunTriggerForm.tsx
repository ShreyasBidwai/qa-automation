import { useRef, useState, type FormEvent } from "react";

import { Link } from "@/components/Link";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { projectApi, runApi } from "@/lib/api/client";
import type {
  AuthoringLayer,
  CsvImportResponse,
  RunCreateBody,
  RunLayer,
  SelectionStrategy,
} from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

type Mode = "describe" | "autonomous";

// Examples are layer-specific: a UI journey reads as a user flow across pages, an
// API contract as an endpoint's request→response behaviour.
const EXAMPLES: Record<AuthoringLayer, string[]> = {
  ui: [
    "a shopper checks out with an expired card",
    "login rejects a wrong password",
    "the dashboard loads after signing in",
  ],
  api: [
    "the orders endpoint rejects an unauthenticated POST",
    "creating an order validates the quantity",
    "the login endpoint returns a token",
  ],
};

// The authoring engine for a "Describe it" run (Mode C). UI composes a browser
// page-journey; API authors the resolved endpoint's contract tests.
const AUTHORING_LAYERS: {
  key: AuthoringLayer;
  title: string;
  description: string;
}[] = [
  {
    key: "ui",
    title: "UI journey",
    description: "a browser flow across pages",
  },
  {
    key: "api",
    title: "API contract",
    description: "an endpoint's request/response",
  },
];

// The selectable layer scope (ADR-0052), in a stable order for a deterministic body.
const LAYERS: { key: RunLayer; label: string; description: string }[] = [
  { key: "ui", label: "UI", description: "page / browser journeys" },
  { key: "api", label: "API", description: "endpoint contracts" },
  { key: "db", label: "DB", description: "database-state checks" },
];

/** Start a run (#4): describe it (Mode C) or run autonomously (Mode B). */
export function RunTriggerForm({ projectId }: { projectId: string }) {
  const [mode, setMode] = useState<Mode>("describe");
  const [prompt, setPrompt] = useState("");
  // Which authoring engine "Describe it" uses (Mode C): UI journey vs API contract.
  const [authoringLayer, setAuthoringLayer] = useState<AuthoringLayer>("ui");
  const [strategy, setStrategy] = useState<SelectionStrategy>("full_sweep");
  const [changeset, setChangeset] = useState("");
  // Layer scope (Mode B). Default = all on = the full set = current behaviour.
  const [layers, setLayers] = useState<Record<RunLayer, boolean>>({
    ui: true,
    api: true,
    db: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function buildBody(): RunCreateBody | null {
    if (mode === "describe") {
      if (!prompt.trim()) {
        setError("Describe what to test.");
        return null;
      }
      return { mode: "mode_c", prompt: prompt.trim(), layer: authoringLayer };
    }

    // At least one layer must be selected; turning all off blocks the run.
    const selectedLayers = LAYERS.map((layer) => layer.key).filter(
      (key) => layers[key],
    );
    if (selectedLayers.length === 0) {
      setError("Select at least one layer to test");
      return null;
    }
    // Omit the field when every layer is on — that equals the full set, so the
    // request body is identical to the existing full-scope behaviour.
    const layerScope: { layers?: RunLayer[] } =
      selectedLayers.length === LAYERS.length ? {} : { layers: selectedLayers };

    if (strategy === "change_impact") {
      const paths = changeset
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (paths.length === 0) {
        setError("List at least one changed file for change-impact selection.");
        return null;
      }
      return { mode: "mode_b", strategy, changeset: paths, ...layerScope };
    }
    return { mode: "mode_b", strategy, ...layerScope };
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
      // "Describe it" AUTHORS tests (no run/findings), so land on the Tests viewer —
      // it polls the authoring job and reveals the new cases the moment they land,
      // instead of an empty live-run page. An autonomous run IS watchable, so it goes
      // straight to the live view (Polaris driving the site, page-by-page).
      if (body.mode === "mode_c") {
        navigate(
          `/projects/${projectId}/tests?authoring=${result.data.run_id}`,
        );
      } else {
        navigate(`/runs/${result.data.run_id}/live`);
      }
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
          description="Say a scenario in plain English — Polaris authors the test (UI journey or API contract) for you to review."
        />
        <ModeCard
          selected={mode === "autonomous"}
          onSelect={() => setMode("autonomous")}
          title="Autonomous"
          description="Polaris sweeps your app and runs tests across the layers you choose."
        />
      </div>

      {mode === "describe" ? (
        <div className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium text-foreground">
              What kind of test
            </legend>
            <div
              role="radiogroup"
              aria-label="Authoring layer"
              className="grid gap-2 sm:grid-cols-2"
            >
              {AUTHORING_LAYERS.map((layer) => (
                <LayerChoice
                  key={layer.key}
                  selected={authoringLayer === layer.key}
                  onSelect={() => setAuthoringLayer(layer.key)}
                  title={layer.title}
                  description={layer.description}
                />
              ))}
            </div>
          </fieldset>

          <div className="space-y-2">
            <label
              htmlFor="prompt"
              className="text-sm font-medium text-foreground"
            >
              What to test
            </label>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={
                authoringLayer === "api"
                  ? "e.g. the orders endpoint rejects an unauthenticated POST"
                  : "e.g. a shopper checks out with an expired card"
              }
              rows={3}
            />
            <div className="flex flex-wrap gap-2">
              {EXAMPLES[authoringLayer].map((example) => (
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

          <CsvImportPanel projectId={projectId} />
        </div>
      ) : (
        <fieldset className="space-y-3">
          <legend className="mb-1 text-sm font-medium text-foreground">
            Scope
          </legend>
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
              <p className="text-xs text-muted-foreground">
                One path per line.
              </p>
            </div>
          ) : null}

          <fieldset className="space-y-2 pt-1">
            <legend className="mb-1 text-sm font-medium text-foreground">
              Layers to test
            </legend>
            <p className="mb-2 text-xs text-muted-foreground">
              Which layers this run exercises. All on = test everything.
            </p>
            <div className="grid gap-2 sm:grid-cols-3">
              {LAYERS.map((layer) => (
                <LayerToggle
                  key={layer.key}
                  label={layer.label}
                  description={layer.description}
                  checked={layers[layer.key]}
                  onChange={(checked) =>
                    setLayers((current) => ({
                      ...current,
                      [layer.key]: checked,
                    }))
                  }
                />
              ))}
            </div>
          </fieldset>
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

// A self-contained CSV template the QA can download, fill in, and re-upload — kept
// inline (a data: URI) so it needs no extra route or asset and always matches the
// columns the parser accepts.
const CSV_TEMPLATE =
  "layer,name,method,path,expected_status,payload,description,authenticated,assert_text\n" +
  "api,List orders,GET,api/v1/orders,200,,lists all orders,true,\n" +
  'api,Create order,POST,api/v1/orders,201,"{""qty"": 2}",creates an order,true,\n' +
  'api,Reject empty cart,POST,api/v1/orders,422,"{""qty"": 0}",rejects a zero qty,true,\n' +
  "ui,Login page,,/login,,,the login page loads,,Sign in\n";

const CSV_TEMPLATE_HREF =
  "data:text/csv;charset=utf-8," + encodeURIComponent(CSV_TEMPLATE);

/** Import QA-authored test scenarios from a CSV — a separate action from starting a
 *  run (it persists reusable test cases the QA fully specified). Deterministic
 *  server-side: no AI, so the QA's declared request→status becomes exactly that test. */
function CsvImportPanel({ projectId }: { projectId: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<CsvImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file: File) {
    setError(null);
    setResult(null);
    setImporting(true);
    const response = await projectApi.importTests(projectId, file);
    setImporting(false);
    // Let the QA pick the same file again after a fix (same value → no change event).
    if (inputRef.current) inputRef.current.value = "";
    if (response.ok && response.data) {
      setResult(response.data);
      return;
    }
    setError(response.error ?? "Could not import the CSV.");
  }

  return (
    <div className="rounded-lg border border-dashed border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            Or import from CSV
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Upload QA-authored scenarios — each row becomes a runnable test (API
            endpoint or UI page smoke).{" "}
            <a
              href={CSV_TEMPLATE_HREF}
              download="polaris-tests-template.csv"
              className="text-accent underline-offset-2 hover:underline"
            >
              Download template
            </a>
          </p>
        </div>
        <div className="shrink-0">
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            aria-label="CSV file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void onFile(file);
            }}
          />
          <Button
            type="button"
            variant="outline"
            disabled={importing}
            onClick={() => inputRef.current?.click()}
          >
            {importing ? "Importing…" : "Choose CSV"}
          </Button>
        </div>
      </div>

      {error ? (
        <p role="alert" className="mt-3 text-sm text-status-fail-fg">
          {error}
        </p>
      ) : null}

      {result ? (
        <CsvImportSummary projectId={projectId} result={result} />
      ) : null}
    </div>
  );
}

function CsvImportSummary({
  projectId,
  result,
}: {
  projectId: string;
  result: CsvImportResponse;
}) {
  const persisted = result.created + result.updated;
  return (
    <div className="mt-3 space-y-2 border-t border-border pt-3">
      {persisted > 0 ? (
        <p className="text-sm text-status-pass-fg">
          Imported {persisted} test{persisted === 1 ? "" : "s"} (
          {result.created} new
          {result.updated > 0 ? `, ${result.updated} updated` : ""}).{" "}
          <Link
            to={`/projects/${projectId}/tests`}
            className="text-accent underline-offset-2 hover:underline"
          >
            View tests →
          </Link>
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          No tests imported — fix the rows below and try again.
        </p>
      )}
      {result.errors.length > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-medium text-status-fail-fg">
            {result.errors.length} row{result.errors.length === 1 ? "" : "s"}{" "}
            skipped:
          </p>
          <ul className="space-y-0.5">
            {result.errors.map((rowError) => (
              <li
                key={`${rowError.row}-${rowError.message}`}
                className="text-xs text-muted-foreground"
              >
                <span className="font-mono text-foreground">
                  {rowError.row === 0 ? "file" : `row ${rowError.row}`}
                </span>{" "}
                — {rowError.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** A compact segmented choice for the Describe-it authoring layer (UI / API). */
function LayerChoice({
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
        "rounded-lg border px-3 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
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
      <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
    </button>
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

function LayerToggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 rounded-lg border p-3",
        checked ? "border-accent bg-accent-subtle" : "border-border bg-surface",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-foreground">
          {label}
        </span>
        <span className="block text-xs text-muted-foreground">
          {description}
        </span>
      </span>
    </label>
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
        selected
          ? "border-accent bg-accent-subtle"
          : "border-border bg-surface",
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
        <span className="block text-sm font-medium text-foreground">
          {title}
        </span>
        <span className="block text-xs text-muted-foreground">
          {description}
        </span>
      </span>
    </label>
  );
}
