# app/git — read-only git provider

Lets ingestion run off a **real remote** (Gitea, or any git host) instead of a
hand-supplied local path (Architecture §4: INGESTION reads git, read-only).

- `GitProvider` (`types.py`) — `checkout(repo_url, ref) -> CheckoutHandle` +
  `cleanup(handle)`. **There is no push/write method, ever.**
- `GitCliProvider` (`cli.py`) — shallow-fetches the ref into a temp dir via the
  git CLI (through an injectable `CommandRunner`), checks it out detached, and
  resolves the real HEAD SHA. The temp clone is removed by `cleanup`.
- `url.py` — `authenticated_url` injects a read-only token into an http(s) clone
  URL; `redact_url` strips credentials for anything logged. **The token and the
  credentialed URL are never logged** (only the redacted URL, ref, and SHA).

Generic git only — host-API features (repo listing, webhooks) are **deferred
until needed**, not built here.

## Configuration

- `GIT_TOKEN` — read-only access token (a secret; from the environment / secret
  store, never committed or logged).
- `GIT_TOKEN_USERNAME` — username paired with the token (default `oauth2`;
  Gitea/GitHub accept any username with a token password).

## Wiring

`app/ingestion/git_ingest.py::ingest_from_git` chains
`checkout → LaravelIngester.ingest(path, source_sha=handle.sha) → cleanup`
(cleanup on success **and** failure). Re-pulling the same SHA updates the Brain
in place via the T2.2 idempotent upserts.

## Testing

Fast tests use a **local git fixture repo** created in a temp dir (real `git`,
no network, no live Gitea); `git` is installed in the backend test image.

## Manual smoke (not CI)

Against a live Gitea/host with a real read-only token:

```python
provider = GitCliProvider(token=settings.git_token,
                          token_username=settings.git_token_username)
handle = provider.checkout("https://gitea.example.com/org/repo.git", "main")
try:
    ...  # ingest_from_git wires this to LaravelIngester
finally:
    provider.cleanup(handle)
```

Confirm: the working tree is populated, `handle.sha` matches the remote HEAD,
no credentials appear in any log, and the temp dir is removed afterwards.
