import { AlertTriangle, FolderGit2 } from "lucide-react";
import { useCallback } from "react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { projectApi } from "@/lib/api/client";
import { usePagedList } from "@/lib/usePagedList";

const PAGE_SIZE = 20;

export function ProjectsListPage() {
  const fetchPage = useCallback(
    (offset: number) => projectApi.list({ limit: PAGE_SIZE, offset }),
    [],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: "projects" });

  const register = (
    <Button asChild>
      <Link to="/projects/new">New project</Link>
    </Button>
  );

  return (
    <>
      <PageHeader title="Projects" action={register} />
      <main className="flex-1 px-6 py-8">
        {list.loading ? (
          <SkeletonRows label="Loading projects…" />
        ) : list.error ? (
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load projects"
            description="Polaris couldn't reach the project service. This is usually temporary."
            code={list.error}
            actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
          />
        ) : list.items.length === 0 ? (
          <StatePanel
            icon={FolderGit2}
            title="No projects yet"
            description="Connect a codebase to start. Polaris reads the repo, maps the app, and finds problems before your users do."
            actions={
              <Button asChild>
                <Link to="/projects/new">Connect a codebase</Link>
              </Button>
            }
          />
        ) : (
          <>
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Name</TH>
                  <TH>Repository</TH>
                  <TH>Registered</TH>
                </TR>
              </THead>
              <TBody>
                {list.items.map((project) => (
                  <TR key={project.id}>
                    <TD className="font-medium">
                      <Link
                        to={`/projects/${project.id}`}
                        className="hover:text-accent"
                      >
                        {project.name}
                      </Link>
                    </TD>
                    <TD className="max-w-xs truncate font-mono text-[13px] text-muted-foreground">
                      {project.repo_url}
                    </TD>
                    <TD className="text-muted-foreground">
                      {new Date(project.created_at).toLocaleDateString()}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination
              offset={list.offset}
              pageSize={list.pageSize}
              total={list.total}
              hasPrev={list.hasPrev}
              hasNext={list.hasNext}
              onPrev={list.prev}
              onNext={list.next}
            />
          </>
        )}
      </main>
    </>
  );
}
