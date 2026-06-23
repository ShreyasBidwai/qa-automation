import { AlertTriangle } from "lucide-react";

import { Link } from "@/components/Link";
import { StatePanel } from "@/components/StatePanel";
import { Wordmark } from "@/components/Wordmark";
import { Button } from "@/components/ui/button";

/**
 * The generic error page (design brief screen "States · 500"). Full-screen and
 * self-contained — it's the error-boundary fallback, so it must stand on its own
 * even when the shell around it has failed. Says what happened and how to recover.
 */
export function GenericErrorPage({ errorId }: { errorId?: string }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
      <div className="mb-9">
        <Wordmark size="lg" />
      </div>
      <StatePanel
        icon={AlertTriangle}
        tone="danger"
        size="lg"
        title="Something went wrong on our end"
        description="We hit an unexpected error and our team has been notified. Try again in a moment."
        code={errorId ? `error_id · ${errorId}` : undefined}
        actions={
          <>
            <Button onClick={() => window.location.reload()}>Reload</Button>
            <Button variant="outline" asChild>
              <Link to="/projects">Back to projects</Link>
            </Button>
          </>
        }
      />
    </div>
  );
}
