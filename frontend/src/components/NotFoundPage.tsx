import { Link } from "@/components/Link";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";

/**
 * The 404 (Polaris States.dc.html · 404). Rendered inside the app shell for an
 * authenticated unknown path — the shell already carries the wordmark, so this is
 * the centered "404 · this page doesn't exist" state with a real way back.
 */
export function NotFoundPage() {
  return (
    <div className="flex h-full items-center justify-center px-6 py-12">
      <StatePanel
        size="lg"
        eyebrow="404"
        title="This page doesn't exist"
        description="The link may be broken, or the run or finding it pointed to was removed."
        actions={
          <Button asChild>
            <Link to="/projects">Back to projects</Link>
          </Button>
        }
      />
    </div>
  );
}
