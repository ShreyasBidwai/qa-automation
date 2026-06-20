import { Button } from "@/components/ui/button";

/** A quiet prev/next pager with an "x–y of n" range (design-direction.md). */
export function Pagination({
  offset,
  pageSize,
  total,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
}: {
  offset: number;
  pageSize: number;
  total: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  if (total <= pageSize && offset === 0) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + pageSize, total);
  return (
    <nav className="mt-4 flex items-center justify-between" aria-label="Pagination">
      <span className="text-xs text-muted-foreground">
        {from}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={onPrev} disabled={!hasPrev}>
          Previous
        </Button>
        <Button variant="outline" size="sm" onClick={onNext} disabled={!hasNext}>
          Next
        </Button>
      </div>
    </nav>
  );
}
