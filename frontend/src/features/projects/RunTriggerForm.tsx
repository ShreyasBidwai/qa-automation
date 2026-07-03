import { Loader2, Search } from "lucide-react";
import { useMemo, useRef, useState, type FormEvent } from "react";

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

import { useProjectModules } from "./useProjectModules";

type Mode = "describe" | "autonomous";
// The autonomous scope: a backend strategy, or "modules" (a full sweep narrowed to
// selected feature areas — ADR-0061). "modules" maps to strategy full_sweep + a filter.
type AutoScope = SelectionStrategy | "modules";

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
  // Autonomous scope: sweep everything, only what changed, or specific modules.
  const [scope, setScope] = useState<AutoScope>("full_sweep");
  const [changeset, setChangeset] = useState("");
  // The module keys to test when scope === "modules" (ADR-0061).
  const [selectedModules, setSelectedModules] = useState<string[]>([]);
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

    if (scope === "change_impact") {
      const paths = changeset
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (paths.length === 0) {
        setError("List at least one changed file for change-impact selection.");
        return null;
      }
      return {
        mode: "mode_b",
        strategy: "change_impact",
        changeset: paths,
        ...layerScope,
      };
    }

    if (scope === "modules") {
      if (selectedModules.length === 0) {
        setError("Select at least one module to test.");
        return null;
      }
      // A module scope is a full sweep NARROWED to those feature areas (ADR-0061).
      return {
        mode: "mode_b",
        strategy: "full_sweep",
        modules: selectedModules,
        ...layerScope,
      };
    }

    return { mode: "mode_b", strategy: "full_sweep", ...layerScope };
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
            selected={scope === "full_sweep"}
            onSelect={() => setScope("full_sweep")}
            title="Test everything"
            description="A full sweep across every testable target."
          />
          <StrategyOption
            value="modules"
            selected={scope === "modules"}
            onSelect={() => setScope("modules")}
            title="Test specific modules"
            description="Pick the feature areas to test — their API and/or frontend."
          />
          {scope === "modules" ? (
            <ModulePicker
              projectId={projectId}
              selected={selectedModules}
              onChange={setSelectedModules}
            />
          ) : null}
          <StrategyOption
            value="change_impact"
            selected={scope === "change_impact"}
            onSelect={() => setScope("change_impact")}
            title="Test only what changed"
            description="Change-impact selection from a list of changed files."
          />
          {scope === "change_impact" ? (
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

/**
 * The module picker (ADR-0061): a searchable, multi-select list of the project's
 * feature areas, laid out across the width. Selecting modules narrows the run to
 * those areas — combined with the layer toggles, to just their API and/or frontend.
 * Controlled: the parent owns the selected keys.
 */
function ModulePicker({
  projectId,
  selected,
  onChange,
}: {
  projectId: string;
  selected: string[];
  onChange: (keys: string[]) => void;
}) {
  const { modules, loading, error } = useProjectModules(projectId);
  const [query, setQuery] = useState("");
  const selectedSet = new Set(selected);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return modules;
    return modules.filter(
      (module) =>
        module.label.toLowerCase().includes(needle) ||
        module.key.includes(needle),
    );
  }, [modules, query]);

  function toggle(key: string) {
    onChange(
      selectedSet.has(key)
        ? selected.filter((existing) => existing !== key)
        : [...selected, key],
    );
  }

  if (loading) {
    return (
      <div className="ml-1 flex items-center gap-2 rounded-lg border border-dashed border-border bg-surface px-3 py-4 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading modules…
      </div>
    );
  }
  if (error) {
    return (
      <p
        role="alert"
        className="ml-1 rounded-lg border border-status-fail-border bg-status-fail-bg px-3 py-2.5 text-[13px] text-status-fail-fg"
      >
        {error}
      </p>
    );
  }
  if (modules.length === 0) {
    return (
      <p className="ml-1 rounded-lg border border-dashed border-border bg-surface px-3 py-4 text-center text-[13px] text-muted-foreground">
        No modules yet — build the model first, and the app’s feature areas
        appear here.
      </p>
    );
  }

  return (
    <div className="ml-1 rounded-xl border border-border bg-surface p-3">
      <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5">
        <Search
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search modules…"
          aria-label="Search modules"
          className="w-full bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span aria-live="polite">
          {selected.length} of {modules.length} selected
        </span>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onChange(filtered.map((module) => module.key))}
            className="font-medium text-accent hover:underline"
          >
            Select {query ? "matching" : "all"}
          </button>
          <button
            type="button"
            onClick={() => onChange([])}
            className="font-medium text-muted-foreground hover:text-foreground hover:underline"
          >
            Clear
          </button>
        </div>
      </div>

      <ul className="mt-2 grid max-h-[300px] gap-1.5 overflow-y-auto sm:grid-cols-2 xl:grid-cols-3">
        {filtered.map((module) => {
          const checked = selectedSet.has(module.key);
          return (
            <li key={module.key}>
              <label
                className={cn(
                  "flex cursor-pointer items-center gap-2.5 rounded-lg border px-2.5 py-2",
                  checked
                    ? "border-accent bg-accent-subtle"
                    : "border-border bg-surface hover:bg-background",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(module.key)}
                  className="h-4 w-4 shrink-0 text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-foreground">
                    {module.label}
                  </span>
                  <span className="block text-[11px] text-status-neutral-solid">
                    {module.endpoint_count} API · {module.page_count} UI
                  </span>
                </span>
              </label>
            </li>
          );
        })}
        {filtered.length === 0 ? (
          <li className="col-span-full px-1 py-3 text-center text-[13px] text-muted-foreground">
            No modules match “{query}”.
          </li>
        ) : null}
      </ul>
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
