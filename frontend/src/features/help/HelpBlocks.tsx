import { ArrowRight } from "lucide-react";
import { Fragment } from "react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { HelpBlock, TrustMark } from "./helpContent";

/**
 * Renders the structured help blocks (helpContent.ts) into the design system.
 * One switch over block kinds — kept in lockstep with the indexer in
 * helpSearch.ts (blockText). Restyling later only touches this file; the content
 * data and the search logic are untouched.
 */
export function HelpBlocks({ blocks }: { blocks: HelpBlock[] }) {
  return (
    <div className="space-y-4">
      {blocks.map((block, index) => (
        <BlockView key={index} block={block} />
      ))}
    </div>
  );
}

function BlockView({ block }: { block: HelpBlock }) {
  switch (block.kind) {
    case "text":
      return <p className="text-sm leading-relaxed text-foreground">{block.text}</p>;
    case "list":
      return (
        <ul className="ml-4 list-disc space-y-1 text-sm text-foreground marker:text-muted-foreground">
          {block.items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      );
    case "steps":
      return (
        <ol className="space-y-2.5">
          {block.items.map((step, i) => (
            <li key={i} className="flex gap-3">
              <span
                className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-status-neutral-bg text-[11px] font-medium text-status-neutral-fg"
                aria-hidden="true"
              >
                {i + 1}
              </span>
              <span className="text-sm leading-relaxed text-foreground">
                <span className="font-medium">{step.label}</span>
                <span className="text-muted-foreground"> — {step.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      );
    case "example":
      return (
        <aside className="rounded-md border border-border bg-background px-4 py-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Example
          </p>
          <p className="mt-1 text-sm leading-relaxed text-foreground">{block.text}</p>
        </aside>
      );
    case "trustMarks":
      return (
        <ul className="space-y-3">
          {block.items.map((mark) => (
            <li key={mark.name} className="flex gap-3">
              <TrustGlyph variant={mark.variant} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge level={glyphLevel(mark.variant)}>{mark.name}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {mark.color} · {mark.strength}
                  </span>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-foreground">
                  {mark.meaning}
                </p>
              </div>
            </li>
          ))}
        </ul>
      );
    case "blastPath":
      return (
        <div className="space-y-2">
          <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
            {block.nodes.map((node, i) => (
              <Fragment key={`${node.tier}-${i}`}>
                <div
                  className={cn(
                    "min-w-[120px] rounded-md border px-3 py-2",
                    i === block.failingIndex
                      ? "border-status-fail-solid bg-status-fail-bg"
                      : "border-border bg-surface",
                  )}
                >
                  <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    {node.tier}
                  </div>
                  <div
                    className={cn(
                      "mt-0.5 break-all font-mono text-[13px]",
                      i === block.failingIndex
                        ? "text-status-fail-fg"
                        : "text-foreground",
                    )}
                  >
                    {node.label}
                  </div>
                  {i === block.failingIndex ? (
                    <div className="mt-1 text-[11px] font-medium text-status-fail-fg">
                      failing here
                    </div>
                  ) : null}
                </div>
                {i < block.nodes.length - 1 ? (
                  <ArrowRight
                    className="h-4 w-4 shrink-0 self-center text-muted-foreground"
                    aria-hidden="true"
                  />
                ) : null}
              </Fragment>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{block.caption}</p>
        </div>
      );
    case "definitions":
      return (
        <dl className="divide-y divide-border rounded-md border border-border">
          {block.items.map((def) => (
            <div
              key={def.term}
              className="grid gap-1 px-4 py-3 sm:grid-cols-[180px_1fr] sm:gap-4"
            >
              <dt className="text-sm font-medium text-foreground">{def.term}</dt>
              <dd className="text-sm leading-relaxed text-muted-foreground">
                {def.definition}
              </dd>
            </div>
          ))}
        </dl>
      );
    default: {
      const _never: never = block;
      return _never;
    }
  }
}

/** solid → emerald/pass, hollow → amber/flaky, ring → blue/info (matches findingBadges). */
function glyphLevel(variant: TrustMark["variant"]): BadgeProps["level"] {
  switch (variant) {
    case "solid":
      return "pass";
    case "hollow":
      return "flaky";
    case "ring":
      return "info";
  }
}

/**
 * The trust-mark glyph. Colour is never the only signal — it always sits next to
 * the name badge and the meaning text — but the shape encodes the mark: a solid
 * disc (strong), a hollow ring (weak), or a ring with a core (anchored).
 */
function TrustGlyph({ variant }: { variant: TrustMark["variant"] }) {
  if (variant === "solid") {
    return (
      <span
        className="mt-1 h-3.5 w-3.5 shrink-0 rounded-full bg-status-pass-solid"
        aria-hidden="true"
      />
    );
  }
  if (variant === "hollow") {
    return (
      <span
        className="mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 border-status-flaky-solid bg-transparent"
        aria-hidden="true"
      />
    );
  }
  return (
    <span
      className="mt-1 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border-2 border-status-info-solid"
      aria-hidden="true"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-status-info-solid" />
    </span>
  );
}
