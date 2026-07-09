import { Search } from "lucide-react";
import { type KeyboardEvent, useMemo, useRef, useState } from "react";

import { PageShell } from "@/components/PageShell";
import { Input } from "@/components/ui/input";

import { HelpBlocks } from "./HelpBlocks";
import { HELP_SECTIONS } from "./helpContent";
import { searchSections } from "./helpSearch";

/** Motion is functional only — honour the OS reduced-motion preference (jsdom-safe). */
function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * The Help center (design brief screen 8c). A searchable, section-wise reference.
 * The search box filters the section list (over titles + body text) and, on
 * select, jumps to that section in the full content on the right. Content lives
 * as structured data (helpContent.ts); search is a pure function (helpSearch.ts).
 */
export function HelpCenterPage() {
  const [query, setQuery] = useState("");
  const headings = useRef<Map<string, HTMLHeadingElement>>(new Map());

  const matches = useMemo(() => searchSections(HELP_SECTIONS, query), [query]);

  function jumpTo(id: string) {
    const heading = headings.current.get(id);
    if (!heading) return;
    heading.scrollIntoView?.({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
    // Move focus so keyboard and screen-reader users land on the section, not
    // back at the top of the page.
    heading.focus({ preventScroll: true });
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && matches.length > 0) {
      event.preventDefault();
      jumpTo(matches[0].id);
    }
  }

  return (
    <PageShell
      scroll={false}
      maxWidth="max-w-5xl"
      header={
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
            Help
          </h1>
          <p className="mt-0.5 text-[13px] text-status-neutral-solid">
            What Polaris is, how it works, and what every symbol means.
          </p>
        </div>
      }
    >
      {/* The two-column area fills the viewport (ADR-0066): each column scrolls
          INTERNALLY instead of a sticky nav + a tall page-body scrollbar. */}
      <div className="flex min-h-0 flex-1 flex-col gap-8 lg:flex-row">
        {/* Left: search + filtered section list (the navigator). */}
        <nav
          aria-label="Help sections"
          className="flex min-h-0 flex-col lg:w-72 lg:shrink-0"
        >
          <div className="shrink-0">
            <label htmlFor="help-search" className="sr-only">
              Search help
            </label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                id="help-search"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onSearchKeyDown}
                placeholder="Search help…"
                className="pl-9"
                autoComplete="off"
                aria-controls="help-section-list"
              />
            </div>

            {query.trim() ? (
              <p className="mt-2 px-1 text-xs text-muted-foreground" role="status">
                {matches.length} of {HELP_SECTIONS.length} sections
              </p>
            ) : null}
          </div>

          {/* The section list is the overflow — it scrolls inside the nav. */}
          <ul
            id="help-section-list"
            className="mt-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto"
          >
            {matches.length === 0 ? (
              <li className="px-3 py-2 text-sm text-muted-foreground">
                No sections match “{query.trim()}”. Try a word like trust, severity, or
                scope.
              </li>
            ) : (
              matches.map((section) => (
                <li key={section.id}>
                  <button
                    type="button"
                    onClick={() => jumpTo(section.id)}
                    className="w-full rounded-md px-3 py-2 text-left text-sm text-foreground hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    <span className="block font-medium">{section.title}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {section.summary}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </nav>

        {/* Right: the full reference. Every section is anchored so jumps always land;
            it's the other overflow region and scrolls on its own. */}
        <div className="min-h-0 min-w-0 flex-1 space-y-10 overflow-y-auto">
          {HELP_SECTIONS.map((section) => {
            const headingId = `help-${section.id}`;
            return (
              <section key={section.id} aria-labelledby={headingId}>
                <h2
                  id={headingId}
                  tabIndex={-1}
                  ref={(el) => {
                    if (el) headings.current.set(section.id, el);
                    else headings.current.delete(section.id);
                  }}
                  className="scroll-mt-24 text-lg font-medium tracking-tight text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-4 focus-visible:ring-offset-background"
                >
                  {section.title}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">{section.summary}</p>
                <div className="mt-4">
                  <HelpBlocks blocks={section.body} />
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </PageShell>
  );
}
