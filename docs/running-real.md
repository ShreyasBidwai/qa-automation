# Running REAL execution against a real Laravel target

`make up-real` brings up the stub stack PLUS a **runner** worker built from the
toolchain image (`backend/Dockerfile` target `real`): PHP 8.2 + Composer, Node +
Playwright + chromium, fastembed (local embeddings, baked in), and git. Generation
calls `claude -p` on the **host** via a small bridge daemon (`make bridge`) — so the
container keeps using your Claude subscription **without mounting `~/.claude`** (a
read-write, cross-uid mount corrupts/rotates the host's OAuth token and logs you out
on every up/down). The slim **backend** still just enqueues; the runner drains the
durable `jobs` queue and executes runs as subprocesses of its own process (ADR-0036).
`make up` (stub) is untouched.

> NEVER target production (`https://mumbaisabha.org`). Only the QA env
> `https://msqa.unifyams.ai/`. First run keeps DB-state tier **off** (default) — no
> DB writes.

## 1. Authenticate `claude` on the host

The bridge runs `claude -p` as **you**, on the host — so just make sure the host
login works (no mounting, no per-container login):

```bash
claude --version            # 2.x
printf 'say ok' | claude -p # should print a reply (proves you're logged in)
```

## 2. Fill the secrets in `.env` (gitignored — never committed)

```bash
cp -n .env.example .env   # if you don't have one

# Fernet key for target-account credentials at rest:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Shared secret the runner uses to call the host bridge:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

In `.env` set (uncomment):

```
CLAUDE_BRIDGE_TOKEN=<paste the token_urlsafe secret>
TARGET_CREDENTIALS_KEY=<paste the generated Fernet key>
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

## 4. Start the bridge, then bring up the real stack

The bridge is a host daemon — run it in its OWN terminal and leave it running
(it holds your Claude login on the host; the runner calls it):

```bash
make bridge      # terminal A — "claude-bridge listening on 0.0.0.0:8787"; keep it up
```

```bash
make up-real     # terminal B — builds the runner image (first time ~5 min) + waits
docker compose --project-directory . -f infra/docker-compose.app.yml \
  -f infra/docker-compose.real.yml ps          # backend/db/web healthy, runner up
docker logs qa-automation-runner-1 | tail       # "worker: started" executor_mode=orchestrator
```

> Verify the runner can reach the bridge:
> `docker exec qa-automation-runner-1 sh -c 'wget -qO- http://host.docker.internal:8787/health'`
> → `{"status": "ok"}`. If generation fails with "bridge unreachable", the bridge
> isn't running (`make bridge`); "rejected the token" → `CLAUDE_BRIDGE_TOKEN`
> mismatch between `.env` and the runner.

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

1. **Clone-at-ingest IS wired now** — set a project's `repo_url` to a **git URL** and
   ingest clones it **read-only** (shallow, temp dir, cleaned up; `GIT_TOKEN` injected
   at fetch time, redacted from logs; no push path, ever). The local checkout (step 3)
   is now only needed for **Pest execution**, which needs `vendor/` (composer install).
   So ingest can run straight from the Gitea URL; executing the generated tests still
   wants the composer-installed checkout at `/targets/app`.
2. **`claude -p` runs on the host via the bridge** (`make bridge`) — the container
   never mounts `~/.claude`, so it can't corrupt/rotate your host login. Keep the
   bridge process running for the duration of the stack; it serializes calls (one
   `claude` at a time) so concurrent token refreshes can't race. The endpoint spends
   your account, so it's token-guarded — don't expose it beyond localhost. (If you'd
   rather not run a host daemon, set `ANTHROPIC_API_KEY` on the `runner` service and
   drop the bridge — that bills per token instead of your subscription.)
3. **Pest's own test DB** — the run executes `vendor/bin/pest` in the checkout; the
   target app's `phpunit.xml`/`.env.testing` governs its test DB (e.g. sqlite +
   RefreshDatabase). DB-state tier `off` means Polaris does no DB provisioning — the
   app must be runnable against a throwaway test DB on its own.
4. **Playwright is installed + verified but not exercised by a Laravel API run** —
   the Laravel ingestor yields endpoint (API) nodes → Pest. Browser/UI runs against
   `app_url` (Playwright) are a further step (page nodes + a browser run).
5. **Embedding warning** — none expected (model baked in); if you rebuild and see a
   one-off model fetch, it's cached after first build.
