import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";

import { CreateProjectForm } from "./CreateProjectForm";

export function CreateProjectPage() {
  return (
    <>
      <PageHeader
        eyebrow={<Link to="/projects">Projects</Link>}
        title="Register project"
      />
      <main className="flex-1 px-6 py-8">
        <p className="mb-6 max-w-xl text-sm text-muted-foreground">
          Connect a project so Polaris can build its model and run tests. Point it at
          the repository and, optionally, the running app it should exercise.
        </p>
        <CreateProjectForm />
      </main>
    </>
  );
}
