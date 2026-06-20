import { Link } from "@/components/Link";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useProjects } from "@/lib/useRegistry";

export function ProjectsListPage() {
  const projects = useProjects();

  return (
    <>
      <PageHeader
        title="Projects"
        action={
          <Button asChild>
            <Link to="/projects/new">Register project</Link>
          </Button>
        }
      />
      <main className="flex-1 px-6 py-8">
        {projects.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="Register a project to start — connect its repo and running app, then run tests."
            action={
              <Button asChild>
                <Link to="/projects/new">Register project</Link>
              </Button>
            }
          />
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Name</TH>
                <TH>Slug</TH>
                <TH>Registered</TH>
              </TR>
            </THead>
            <TBody>
              {projects.map((project) => (
                <TR key={project.id}>
                  <TD className="font-medium">
                    <Link to={`/projects/${project.id}`} className="hover:text-accent">
                      {project.name}
                    </Link>
                  </TD>
                  <TD className="font-mono text-[13px] text-muted-foreground">
                    {project.slug}
                  </TD>
                  <TD className="text-muted-foreground">
                    {new Date(project.createdAt).toLocaleDateString()}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </main>
    </>
  );
}
