# Running REAL execution against a real Laravel target

`make up-real` brings up the stub stack PLUS a **runner** worker built from the
toolchain image (`backend/Dockerfile` target `real`): PHP 8.2 + Composer, Node +
Playwright + chromium, fastembed (local embeddings, baked in), git, and the host
`claude` CLI bind-mounted on PATH. The slim **backend** still just enqueues; the
runner drains the durable `jobs` queue and executes runs as subprocesses of its own
process (ADR-0036). `make up` (stub) is untouched.

> NEVER target production (`https://mumbaisabha.org`). Only the QA env
> `https://msqa.unifyams.ai/`. First run keeps DB-state tier **off** (default) — no
> DB writes.

## 1. Authenticate `claude` on the host

The runner bind-mounts your host `claude` binary + auth (`~/.claude.json`,
`~/.claude/`). Make sure `claude` works on the host first:

```bash
claude --version            # 2.x
printf 'say ok' | claude -p # should print a reply (proves you're logged in)
```

## 2. Fill the two secrets in `.env` (gitignored — never committed)

```bash
cp -n .env.example .env   # if you don't have one

# Generate the Fernet key for target-account credentials at rest:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In `.env` set (uncomment):

```
TARGET_CREDENTIALS_KEY=<paste the generated key>
GIT_TOKEN=<your Gitea read-only token>
TARGET_REPO_HOST_PATH=./targets/app
```

## 3. Clone + composer-install the target into the bind-mount

> **Honest gap:** clone-at-ingest is not yet wired — ingest reads a **local
> checkout**, and Pest needs `vendor/` present. So check the repo out yourself into
> `./targets/app` (bind-mounted into the runner at `/targets/app`):

```bash
git clone "https://oauth2:${GIT_TOKEN}@git.datagrid.co.in/Datagrid/mumbaisabhaams.git" targets/app
cd targets/app && composer install --no-interaction --prefer-dist && cd -
```

(`targets/` is gitignored.)

## 4. Bring up the real stack

```bash
make up-real     # builds the runner image (first time ~5 min) + waits healthy
docker compose --project-directory . -f infra/docker-compose.app.yml \
  -f infra/docker-compose.real.yml ps          # backend/db/web healthy, runner up
docker logs qa-automation-runner-1 | tail       # "worker: started" executor_mode=orchestrator
```

The console is `http://localhost:8080`. The API is `http://localhost:8080/api/v1`.

## 5. Register the project, ingest, run

Sign up (or use the UI), then create the project pointing at the in-container repo
path + the QA url. `stack=laravel` selects the Pest runner; tier defaults to `off`.

```bash
API=http://localhost:8080/api/v1
TOKEN=$(curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"you@datagrid.co.in","password":"choose-a-strong-one"}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

PID=$(curl -s -X POST $API/projects -H "$AUTH" -H 'Content-Type: application/json' -d '{
  "name":"Mumbai Sabha AMS",
  "repo_url":"/targets/app",
  "app_url":"https://msqa.unifyams.ai/",
  "stack":"laravel"
}' | jq -r .id)
echo "project=$PID"

# Ingest (build the real Brain from the checkout) — runner claims + executes it.
curl -s -X POST $API/projects/$PID/ingest -H "$AUTH" | jq .
# Watch ingest finish (a few seconds → minutes for a large repo):
#   docker logs -f qa-automation-runner-1

# Trigger a real autonomous run, scoped to the API layer (Pest) for the first pass:
RID=$(curl -s -X POST $API/projects/$PID/runs -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"mode":"mode_b","strategy":"full_sweep","layers":["api"]}' | jq -r .run_id)
echo "run=$RID"
```

(Or do all of this in the UI: sign up → New project → Ingest → Run → Autonomous.)

## 6. Watch it

- **Live run view (UI):** `http://localhost:8080/runs/$RID/live` — the journey
  (generate → execute step-by-step → review).
- **Events (API):** `curl -N -H "$AUTH" $API/runs/$RID/events/stream` (SSE) or
  `$API/runs/$RID/events` (replay).
- **Findings:** `$API/runs/$RID/findings`.
- **Failures / incidents:** `curl -H "$AUTH" "$API/incidents?project_id=$PID" | jq` —
  any phase that errored (generation/execution/provider) is captured here with the
  reason; this is where you look first if a run doesn't produce findings.
- **Runner logs:** `docker logs -f qa-automation-runner-1`.

## Remaining gaps / things that may need a fix-up on the first real run

1. **Clone-at-ingest not wired** — you provide the checkout (step 3). When per-project
   clone lands, `GIT_TOKEN` (already plumbed to the runner) will be used + the repo
   token should move to the encrypted credentials vault (ADR-0053/0054).
2. **`claude -p` auth in-container** — `~/.claude*` is mounted read-only. If `claude
   -p` errors trying to write its cache, change those mounts to read-write in
   `infra/docker-compose.real.yml`, or set `ANTHROPIC_API_KEY` on the `runner`
   service instead.
3. **Pest's own test DB** — the run executes `vendor/bin/pest` in the checkout; the
   target app's `phpunit.xml`/`.env.testing` governs its test DB (e.g. sqlite +
   RefreshDatabase). DB-state tier `off` means Polaris does no DB provisioning — the
   app must be runnable against a throwaway test DB on its own.
4. **Playwright is installed + verified but not exercised by a Laravel API run** —
   the Laravel ingestor yields endpoint (API) nodes → Pest. Browser/UI runs against
   `app_url` (Playwright) are a further step (page nodes + a browser run).
5. **Embedding warning** — none expected (model baked in); if you rebuild and see a
   one-off model fetch, it's cached after first build.
