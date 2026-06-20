import { useCallback } from "react";

import { EmptyState } from "@/components/EmptyState";
import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
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
      <Link to="/projects/new">Register project</Link>
    </Button>
  );

  return (
    <>
      <PageHeader title="Projects" action={register} />
      <main className="flex-1 px-6 py-8">
        {list.loading ? (
          <p className="text-sm text-muted-foreground">Loading projects…</p>
        ) : list.error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            Could not load projects. {list.error}
          </p>
        ) : list.items.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="Register a project to start — connect its repo and running app, then run tests."
            action={register}
          />
        ) : (
          <>
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Name</TH>
                  <TH>Slug</TH>
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
                    <TD className="font-mono text-[13px] text-muted-foreground">
                      {project.slug}
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
