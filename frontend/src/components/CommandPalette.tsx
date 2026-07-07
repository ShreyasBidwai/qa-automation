import { FolderGit2, Inbox, ListChecks, Search } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { SearchResultItem, SearchResultType } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

import { useCommandPaletteSearch } from "./useCommandPaletteSearch";

const TYPE_ICON: Record<SearchResultType, typeof FolderGit2> = {
  project: FolderGit2,
  finding: Inbox,
  run: ListChecks,
};

const TYPE_LABEL: Record<SearchResultType, string> = {
  project: "Project",
  finding: "Finding",
  run: "Run",
};

const LIST_ID = "command-palette-listbox";

function optionId(index: number): string {
  return `${LIST_ID}-option-${index}`;
}

/**
 * The ⌘K / Ctrl+K command palette (ADR-0068): an accessible overlay that jumps to a
 * Project / Finding / Run by name via the real, org-scoped search endpoint — never a
 * client-side filter over an already-fetched page. Mirrors the existing `Drawer`
 * overlay's accessibility contract (focus moves in on open + is trapped, Esc closes,
 * focus restores to the trigger) and ADR-0066 (a fixed-position overlay above the
 * page; the window never scrolls).
 */
export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const { results, loading, error } = useCommandPaletteSearch(open ? query : "");
  const inputRef = useRef<HTMLInputElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = (document.activeElement as HTMLElement | null) ?? null;
    setQuery("");
    setActiveIndex(0);
    inputRef.current?.focus();
    return () => {
      restoreRef.current?.focus?.();
    };
  }, [open]);

  // A fresh result set never keeps a stale selection pinned past the end of the list.
  useEffect(() => {
    setActiveIndex(0);
  }, [results]);

  if (!open) return null;

  function go(item: SearchResultItem) {
    onClose();
    navigate(item.url);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key === "Tab") {
      // The input is the only focusable control — keep focus trapped inside it
      // rather than letting Tab escape to the (inert) page behind the overlay.
      event.preventDefault();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (results.length > 0) setActiveIndex((i) => (i + 1) % results.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (results.length > 0) {
        setActiveIndex((i) => (i - 1 + results.length) % results.length);
      }
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const item = results[activeIndex];
      if (item) go(item);
    }
  }

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-foreground/20"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onKeyDown={handleKeyDown}
        className="absolute left-1/2 top-[15%] w-full max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-surface shadow-xl"
      >
        <div className="flex items-center gap-2.5 border-b border-border-subtle px-4">
          <Search
            className="h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls={LIST_ID}
            aria-autocomplete="list"
            aria-activedescendant={
              results[activeIndex] ? optionId(activeIndex) : undefined
            }
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search projects, findings, runs…"
            className="h-12 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
        </div>
        <ul
          id={LIST_ID}
          role="listbox"
          aria-label="Search results"
          className="max-h-80 overflow-y-auto py-1.5"
        >
          {loading ? (
            <li className="px-4 py-6 text-center text-sm text-muted-foreground">
              Searching…
            </li>
          ) : error ? (
            <li className="px-4 py-6 text-center text-sm text-status-fail-fg">
              {error}
            </li>
          ) : query.trim() === "" ? (
            <li className="px-4 py-6 text-center text-sm text-muted-foreground">
              Type to jump to a project, finding, or run.
            </li>
          ) : results.length === 0 ? (
            <li className="px-4 py-6 text-center text-sm text-muted-foreground">
              No results for “{query.trim()}”.
            </li>
          ) : (
            results.map((item, index) => {
              const Icon = TYPE_ICON[item.type];
              return (
                <li
                  key={`${item.type}-${item.id}`}
                  id={optionId(index)}
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => go(item)}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 px-4 py-2.5",
                    index === activeIndex ? "bg-accent-subtle" : "hover:bg-background",
                  )}
                >
                  <Icon
                    className="h-4 w-4 shrink-0 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {item.label}
                    </span>
                    {item.subtitle ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {item.subtitle}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 rounded-[5px] bg-status-neutral-bg px-[7px] py-0.5 text-[10px] font-medium uppercase tracking-wide text-status-neutral-fg">
                    {TYPE_LABEL[item.type]}
                  </span>
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>
  );
}
