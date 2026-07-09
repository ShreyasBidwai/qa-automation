/**
 * Dependency-free, theme-aware SVG chart primitives for the account dashboard.
 *
 * No charting library: each chart is a small, responsive SVG that colours itself from
 * the design-system tokens via `text-…` + `currentColor` (so it tracks light/dark and
 * never hard-codes a hex). Pure/presentational — all data + labels come from props.
 */

import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface DonutSegment {
  key: string;
  label: string;
  value: number;
  /** A `text-…` token class; the arc is drawn with `currentColor`. */
  colorClass: string;
}

/** A donut of proportional segments with a free-form center (total, %, etc.). Renders a
 *  full track ring when everything is zero, so it never collapses to nothing. */
export function DonutChart({
  segments,
  size = 132,
  thickness = 14,
  center,
}: {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  center?: ReactNode;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const radius = (size - thickness) / 2;
  const c = size / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="relative inline-flex" style={{ width: size, height: size }}>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        aria-hidden="true"
      >
        <circle
          cx={c}
          cy={c}
          r={radius}
          fill="none"
          strokeWidth={thickness}
          className="stroke-border-subtle"
        />
        {total > 0 &&
          segments
            .filter((s) => s.value > 0)
            .map((s) => {
              const dash = (s.value / total) * circumference;
              const el = (
                <circle
                  key={s.key}
                  cx={c}
                  cy={c}
                  r={radius}
                  fill="none"
                  strokeWidth={thickness}
                  className={s.colorClass}
                  stroke="currentColor"
                  strokeDasharray={`${dash} ${circumference - dash}`}
                  strokeDashoffset={-offset}
                  transform={`rotate(-90 ${c} ${c})`}
                >
                  <title>{`${s.label}: ${s.value}`}</title>
                </circle>
              );
              offset += dash;
              return el;
            })}
      </svg>
      {center ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {center}
        </div>
      ) : null}
    </div>
  );
}

export interface TrendPointDatum {
  label: string; // x-axis label (e.g. a date)
  value: number | null; // 0..1, or null for a gap (no data that day)
}

/** A smooth-ish area+line of a 0..1 series over time (the pass-rate trend). Nulls break
 *  the line into segments (honest gaps, not interpolated). Responsive via viewBox. */
export function TrendArea({
  points,
  height = 148,
  colorClass = "text-status-pass-solid",
}: {
  points: TrendPointDatum[];
  height?: number;
  colorClass?: string;
}) {
  const width = 640; // viewBox units; the SVG scales to its container width
  const padX = 6;
  const padY = 10;
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;
  const n = points.length;
  const x = (i: number) => (n <= 1 ? padX : padX + (i / (n - 1)) * innerW);
  const y = (v: number) => padY + (1 - Math.max(0, Math.min(1, v))) * innerH;

  // Break into contiguous runs of non-null points so gaps aren't bridged.
  const runs: { i: number; v: number }[][] = [];
  let current: { i: number; v: number }[] = [];
  points.forEach((p, i) => {
    if (p.value === null) {
      if (current.length) runs.push(current);
      current = [];
    } else {
      current.push({ i, v: p.value });
    }
  });
  if (current.length) runs.push(current);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-[148px] w-full"
      role="img"
      aria-label="Pass-rate trend"
    >
      {/* gridlines at 0 / 50 / 100% */}
      {[0, 0.5, 1].map((g) => (
        <line
          key={g}
          x1={padX}
          x2={width - padX}
          y1={y(g)}
          y2={y(g)}
          className="stroke-border-subtle"
          strokeWidth={1}
          strokeDasharray={g === 0 || g === 1 ? undefined : "3 4"}
        />
      ))}
      {runs.map((run, ri) => {
        const line = run
          .map((pt, k) => `${k === 0 ? "M" : "L"} ${x(pt.i)} ${y(pt.v)}`)
          .join(" ");
        const area =
          run.length > 1
            ? `${line} L ${x(run[run.length - 1].i)} ${y(0)} L ${x(run[0].i)} ${y(0)} Z`
            : "";
        return (
          <g key={ri} className={colorClass}>
            {area ? (
              <path d={area} fill="currentColor" className="opacity-[0.12]" />
            ) : null}
            <path
              d={line}
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {run.map((pt) => (
              <circle
                key={pt.i}
                cx={x(pt.i)}
                cy={y(pt.v)}
                r={run.length === 1 ? 3.5 : 2.5}
                fill="currentColor"
              >
                <title>{`${points[pt.i].label}: ${Math.round(pt.v * 100)}%`}</title>
              </circle>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

/** A tiny legend chip: a token-coloured dot + a count + label. */
export function LegendDot({
  colorClass,
  count,
  label,
}: {
  colorClass: string;
  count: number;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span className={cn("h-[7px] w-[7px] rounded-full", colorClass)} />
      <span className="tabular-nums text-foreground">{count}</span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}
