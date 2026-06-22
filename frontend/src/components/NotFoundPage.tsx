import { FileQuestion } from "lucide-react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Not found" />
      <main className="flex-1 px-6 py-8">
        <StatePanel
          icon={FileQuestion}
          eyebrow="404"
          title="This page doesn't exist"
          description="The link may be broken, or the run or finding it pointed to was removed."
          actions={
            <Button asChild>
              <Link to="/projects">Back to projects</Link>
            </Button>
          }
        />
      </main>
    </>
  );
}
