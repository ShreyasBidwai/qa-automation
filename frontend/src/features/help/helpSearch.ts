/**
 * Client-side help search. Pure functions, no React — so the matching logic is
 * unit-testable on its own and the page stays a thin shell over it.
 *
 * The index is built from the content data (helpContent.ts), never from rendered
 * markup, so a section matches on its title, summary, keywords, AND every word of
 * its body. Matching is token-AND and case-insensitive: typing "trust amber"
 * finds the section that contains both words, in any order.
 */

import type { HelpBlock, HelpSection } from "./helpContent";

/** Flatten one block to its searchable text. Mirrors the block kinds in helpContent.ts. */
export function blockText(block: HelpBlock): string {
  switch (block.kind) {
    case "text":
    case "example":
      return block.text;
    case "list":
      return block.items.join(" ");
    case "steps":
      return block.items.map((s) => `${s.label} ${s.detail}`).join(" ");
    case "definitions":
      return block.items.map((d) => `${d.term} ${d.definition}`).join(" ");
    case "trustMarks":
      return block.items
        .map((m) => `${m.symbol} ${m.color} ${m.name} ${m.strength} ${m.meaning}`)
        .join(" ");
    case "blastPath":
      return `${block.nodes.map((n) => `${n.tier} ${n.label}`).join(" ")} ${block.caption}`;
    default: {
      // Exhaustiveness guard: a new block kind must be handled above.
      const _never: never = block;
      return _never;
    }
  }
}

/** The full lowercased haystack for one section: title + summary + keywords + body. */
export function sectionSearchText(section: HelpSection): string {
  const parts = [
    section.title,
    section.summary,
    ...(section.keywords ?? []),
    ...section.body.map(blockText),
  ];
  return parts.join(" ").toLowerCase();
}

/** Split a query into lowercased, non-empty tokens. */
export function queryTokens(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/**
 * Filter sections to those whose searchable text contains every query token.
 * An empty (or whitespace-only) query returns all sections, in their natural
 * order — the page reads as a full reference until you start typing.
 */
export function searchSections(sections: HelpSection[], query: string): HelpSection[] {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return sections;
  return sections.filter((section) => {
    const haystack = sectionSearchText(section);
    return tokens.every((token) => haystack.includes(token));
  });
}
