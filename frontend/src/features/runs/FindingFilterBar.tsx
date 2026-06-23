import { ALL, type FindingFilters } from "./findingFilters";

/**
 * The shared finding-filter pills (severity / layer / trust / status) plus the
 * "hide muted" toggle — the exact control used by the run dashboard and the
 * findings inbox, so the two screens filter identically (Polaris *.dc.html). A
 * filter as a pill-styled native select; it shows the filter name until set.
 */
export function FindingFilterBar({
  filters,
  onChange,
}: {
  filters: FindingFilters;
  onChange: (next: FindingFilters) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-[7px]">
      <FilterPill
        name="Severity"
        value={filters.severity}
        onChange={(v) => onChange({ ...filters, severity: v })}
        options={[
          ["critical", "Critical"],
          ["major", "Major"],
          ["minor", "Minor"],
        ]}
      />
      <FilterPill
        name="Layer"
        value={filters.layer}
        onChange={(v) => onChange({ ...filters, layer: v })}
        options={[
          ["ui", "ui"],
          ["api", "api"],
          ["db", "db"],
        ]}
      />
      <FilterPill
        name="Trust"
        value={filters.confidence}
        onChange={(v) => onChange({ ...filters, confidence: v })}
        options={[
          ["rule-derived", "Rule-derived"],
          ["characterization", "Characterization"],
          ["spec-grounded", "Spec-grounded"],
        ]}
      />
      <FilterPill
        name="Status"
        value={filters.status}
        onChange={(v) => onChange({ ...filters, status: v })}
        options={[
          ["new", "New"],
          ["regression", "Regression"],
          ["flaky", "Flaky"],
          ["known", "Known"],
        ]}
      />
      <HideMutedToggle
        checked={filters.hideMuted}
        onChange={(hide) => onChange({ ...filters, hideMuted: hide })}
      />
    </div>
  );
}

function FilterPill({
  name,
  value,
  onChange,
  options,
}: {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      aria-label={name}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-[7px] border border-border bg-background py-1 pl-2.5 pr-1.5 text-xs font-medium text-status-neutral-fg transition-colors focus-visible:border-accent"
    >
      <option value={ALL}>{name}</option>
      {options.map(([optionValue, optionLabel]) => (
        <option key={optionValue} value={optionValue}>
          {optionLabel}
        </option>
      ))}
    </select>
  );
}

function HideMutedToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="ml-1 inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-muted-foreground">
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="relative h-4 w-[26px] rounded-full bg-border transition-colors peer-checked:bg-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent">
        <span className="absolute left-0.5 top-0.5 h-3 w-3 rounded-full bg-surface transition-transform peer-checked:translate-x-2.5" />
      </span>
      Hide muted
    </label>
  );
}
