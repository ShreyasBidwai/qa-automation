# ADR-0053: Encrypted target-account credentials for specific-account testing

- Status: Accepted
- Date: 2026-06-24
- Deciders: Engineering

## Context

A project may want its runs to test a SPECIFIC existing account in the target app
(the user supplies a mobile/email + password) instead of having Polaris provision its
own account. We must store those credentials so a run can authenticate as that
account. This handles **real secrets**, so the secret-handling model is the point of
this slice and is non-negotiable.

## Decision — the secret-handling model

### Encrypted at rest from line one (key from config, never the repo)

The account secret is **encrypted before it touches the DB** and stored ONLY as
ciphertext. Encryption is **Fernet** (AES-128-CBC + HMAC-SHA256, authenticated) via a
single module, `app.credentials.crypto`. The key is `Settings.target_credentials_key`
— a urlsafe-base64 32-byte Fernet key sourced from the **environment / secret store**,
never hardcoded and never in the repo. Hard rule: **if no key is configured,
encryption RAISES** (`CredentialsKeyError`) and the write path returns 503 — nothing
is ever stored in the clear ("if you can't encrypt it, don't store it"). The
`target_credentials.encrypted_secret` column is `bytea`, so the value is opaque even
to a DB inspector; plaintext never reaches the table.

### Write-only secret — never returned in any payload

The secret is write-only. `PUT` accepts it (as a Pydantic `SecretStr`, so it is masked
in any body repr/log) and encrypts it; **no** payload ever returns it. `GET
/projects/{id}/credentials` returns only `{mode, identifier, has_credentials}` — its
response model (`CredentialStatusResponse`) has **no secret field**, so FastAPI cannot
serialize one even by mistake (defence in depth). `has_credentials` is true iff an
encrypted secret is stored.

### Never logged / in errors / in events

The secret is never logged, put in an error message, an incident capture, or a
run-progress event. The run path records only the chosen `auth_mode`
(`specific_account` / `polaris_creates`) — never the secret or the identifier. The
decrypt-at-use result type (`ResolvedTargetLogin`) overrides `repr`/`str` to render
`secret=***` and a redacted identifier, so it can't leak through an f-string,
traceback, or log line. Decryption errors surface as a generic message carrying no
plaintext.

### Decrypted ONLY at the point of use

`app.credentials.resolver.resolve_target_login` is the **only** place a stored secret
is decrypted — in memory, when a run authenticates, never persisted decrypted and
never passed through a logging layer. Every other path (read, list, status) treats the
ciphertext as opaque. `crypto.decrypt_secret` is called from nowhere else.

### RBAC

Setting, viewing, and clearing credentials are all gated on **MANAGE_PROJECT**. GET is
manage-gated too (not VIEW) because the identifier is account PII and credential
configuration is a project-management action — the conservative choice.

### Data model + run-path selection

`target_credentials` (migration `0031`, linear off `0030`): one row per project
(unique `project_id`, `ON DELETE CASCADE`), `mode`, nullable `identifier`
(email/mobile — returnable), nullable `encrypted_secret` (bytea). `PUT/GET/DELETE
/projects/{id}/credentials`. The run path (`OrchestratorRunExecutor`) resolves the
mode: a `specific_account` project with complete credentials authenticates as that
account; otherwise Polaris provisions its own (existing behaviour). The actual
target-auth mechanics are **stubbed** — the AuthStrategy login flow (T4.2a) is not yet
wired into runs — but the selection is wired and the resolved login is obtained
without leaking the secret.

## Consequences

- A target secret exists in the clear only transiently in memory, at the one point of
  use; at rest it is always Fernet ciphertext under a config key.
- No payload, log, error, or event can return the secret; the read model structurally
  cannot.
- A missing key fails closed (no plaintext fallback).
- Key management (rotation, per-tenant keys, a real KMS) is out of scope here; the key
  is a single app secret from config. Rotating it would require re-encrypting stored
  secrets — noted for a follow-up.

## Honest limitations

- Single symmetric app key (not per-project, no envelope encryption / KMS). Adequate
  for this slice; a KMS + key rotation is the production hardening follow-up.
- The `identifier` is stored in plaintext (it is returnable by design); it is redacted
  in logs but is readable by MANAGE_PROJECT members and a DB inspector.
