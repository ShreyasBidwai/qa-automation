# Running Polaris (local / demo / internal)

Clone → a running Polaris: Postgres + backend + the operator console, on one
URL. This is the **local / demo / internal** stack — honest and simple, **not**
production Kubernetes. It boots with **zero external credentials**: the run and
ingest paths default to safe stubs, so you can click through the whole product
(create a project → trigger a run → triage findings) without any AI keys or test
toolchains.

## Prerequisites

- **Docker** with the **Compose v2** plugin (`docker compose …`). Nothing else —
  no local Python, Node, Postgres, or browsers required.
- ~2 GB free disk for images + the Postgres volume.

## Bring it up

```bash
git clone <repo> && cd qa-automation
cp .env.example .env          # optional — every value has a built-in default
make up                       # build + start, wait until healthy
```

`make up` runs:

```
docker compose --project-directory . -f infra/docker-compose.app.yml up -d --build --wait
```

It starts three services:

| Service   | What it is                                              | Default URL / port |
|-----------|--------------------------------------------------------|--------------------|
| `db`      | Postgres 16 + pgvector, persistent named volume        | `localhost:5434`   |
| `backend` | FastAPI control plane; **applies migrations on start** | (internal :8000)   |
| `web`     | The built operator console (nginx), **single-origin**  | **http://localhost:8080** |

Open **http://localhost:8080**.

**Single-origin:** one nginx serves the built SPA and reverse-proxies
`/api`, `/healthz`, `/readyz` to the backend — no CORS, one URL, and the client's
default relative API base (`/api/v1`) just works. The backend is not published to
the host by this stack; reach it through the web origin.

Migrations apply automatically when the backend container starts
(`alembic upgrade head` before the server). The documented one-shot, if you ever
want it explicitly, is `make migrate`.

Tear down (the Postgres volume persists):

```bash
make down
```

## First-run walkthrough

In the UI at **http://localhost:8080**:

1. **Create a project.** Projects → *New project*. Give it a name and a repo URL
   (any URL is fine for the stub path; for a real target later, this is where
   AAHOA's repo/app URLs go). It appears in the projects list.
2. **Ingest** (build the Brain). On the project page, *Ingest*. With the default
   stub ingestor this completes instantly and records an honest "no Brain built"
   summary — enough to exercise the flow end-to-end.
3. **Trigger a run.** *Run* → Autonomous (Mode B), full sweep. The stub executor
   completes the run and produces **one fabricated demo finding** (clearly
   labelled a stub) so the whole finding experience is live.
4. **See the findings.** Open the run → the dashboard lists the finding. Click it
   for the detail drawer: cross-layer location, evidence with the trust badge,
   cross-run history, and **working triage actions** (acknowledge / resolve /
   won't-fix). Triage a finding and re-open the drawer — the disposition sticks.

The same flow headless (proves the running stack, no browser):

```bash
BASE=http://localhost:8080/api/v1

# create a project
PID=$(curl -s -X POST $BASE/projects -H 'content-type: application/json' \
  -d '{"name":"Demo","repo_url":"https://example.test/repo.git"}' | jq -r .id)

# trigger an autonomous run; the job handle is the run_id we poll
RID=$(curl -s -X POST $BASE/projects/$PID/runs -H 'content-type: application/json' \
  -d '{"mode":"mode_b","strategy":"full_sweep"}' | jq -r .run_id)

# poll until it succeeds, then read the findings
curl -s $BASE/runs/$RID            # -> {"status":"succeeded", ...}
curl -s $BASE/runs/$RID/findings   # -> one stub finding with triage:{status:"open"}
```

## Configuration

Everything is environment-driven (`.env`, defaults baked in). The knobs that
matter for running:

| Variable          | Default | Meaning |
|-------------------|---------|---------|
| `WEB_PORT`        | `8080`  | Host port for the operator console. |
| `POSTGRES_*`      | local placeholders | DB name / user / password (change for anything shared). |
| `EXECUTOR_MODE`   | `stub`  | `stub` fabricates a demo finding; `orchestrator` runs real tests (needs toolchains — see limitations). |
| `INGESTOR_MODE`   | `stub`  | `stub` builds no Brain; `laravel` does real ingestion (needs git + adapter). |
| `AI_PROVIDER_MODE`| `stub`  | `stub` needs no creds; `claude_cli` shells to the `claude` CLI (**not shipped in this image**). |
| `EMBEDDING_PROVIDER` | `stub` | `stub` (no download) or `local` (fastembed ONNX). |
| `GIT_TOKEN`       | unset   | Read-only token for private-repo ingestion; injected at clone time, never logged. |

**Switching to real AI (`claude_cli`):** the packaged backend image ships **no**
`claude` CLI. Using it means providing the CLI on the backend's PATH (bind-mount
or a derived image) and setting `AI_PROVIDER_MODE=claude_cli`. Out of scope for
the packaged image; the seam is there.

## How runs actually execute (and why the defaults are stubs)

**Finding before building:** the backend invokes a Pest / Playwright run as a
**subprocess of its own process** (`app/execution/*.py` →
`subprocess.run(["…/vendor/bin/pest", …])` / `node_modules/.bin/playwright`). It
is **not** `docker run` against a runner image and **not** a separate runner
service — the toolchains must be present on the backend's own PATH, and Playwright
additionally needs a running target frontend at a `base_url`. The runner images
under `runners/` (Laravel, Playwright) are used by the real-tooling **test** lanes
(`make test-runners`, `make test-e2e-runner`), not by the API at request time.

That makes a clean container story for **real** runs genuinely messy: the
control-plane backend would need PHP+Pest **and** Node+Playwright+browsers baked
in, plus a bootable test-backed target app. So the packaged stack does the
pragmatic, honest thing — it ships the backend **without** those toolchains and
**defaults the run/ingest ports to stubs** (`EXECUTOR_MODE=stub`,
`INGESTOR_MODE=stub`), which is enough to demo and operate the whole product. Real
execution is a deliberate opt-in, documented here rather than half-wired.

## Limitations (honest)

- **Stub run/ingest by default.** Out of the box a "run" fabricates one demo
  finding and "ingest" builds no Brain. Real runs need the orchestrator + the
  Pest/Playwright toolchains co-located with the backend (per the execution model
  above); real ingestion needs git + the source adapter. Both are config seams
  (`EXECUTOR_MODE` / `INGESTOR_MODE`), not wired into this image.
- **In-memory job registry (Tier 2).** Ingest/run jobs are tracked in a per-process
  dict (ADR-0026). It is **not durable** — a backend restart loses in-flight job
  handles (persisted projects/runs/findings survive in Postgres). A real broker +
  `jobs` table is the Tier-2 upgrade behind the same poll contract.
- **No user auth yet (Tier 2).** There is no sign-in; the API is unauthenticated
  and triage records `triaged_at` but not *who* (no fake actor — ADR-0027). Run
  this on a trusted network only.
- **nginx resolves the backend at startup.** If you restart only the `backend`
  container, restart `web` too so nginx repoints. (`make down && make up` is fine.)

## Pointing Polaris at a real target (e.g. AAHOA)

Stand the stack up as above, create a project whose `repo_url` / `app_url` point
at the target, then flip the relevant provider(s) off `stub` once the matching
prerequisites are in place (git token for ingestion; the runner toolchains for
real execution). The packaging is target-agnostic — the only target-specific
input is the project's repo/app URLs.

## Developing the UI (separate from packaging)

For Vite hot-reload while working on the frontend, use the dev stack instead:

```bash
make dev-up     # backend :8000 + Vite dev server :5173
make dev-down
```
