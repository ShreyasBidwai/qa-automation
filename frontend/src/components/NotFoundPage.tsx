import { Link } from "@/components/Link";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Not found" />
      <main className="flex-1 px-6 py-8">
        <EmptyState
          title="This page doesn't exist"
          description="The link may be out of date."
          action={
            <Button asChild>
              <Link to="/projects">Back to projects</Link>
            </Button>
          }
        />
      </main>
    </>
  );
}
