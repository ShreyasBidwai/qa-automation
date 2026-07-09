# Future scope — parked follow-ups (go-to-market initiative)

The operator console, access control, pricing/billing, and the self-improvement flywheel
shipped in the `feat/platform-operator-admin` branch. This file parks the follow-ups that
were **deliberately deferred** — each is documented at the code seam it extends, with why
it was deferred and roughly what it takes. None block launch; they are the next horizon.

## 1. Live Stripe payment (B6) — *blocked on a key, seam ready*

- **State:** the env seam is wired (`billing_mode`, `stripe_api_key`, `stripe_webhook_secret`
  in `app/core/config.py`; placeholders in `.env.example`). Plans are seeded + staff-
  assignable (ADR-0069), so billing *functions* — only live card collection is inert.
- **To land:** set `STRIPE_API_KEY` + `BILLING_MODE=stripe`, then implement a
  `StripeBillingProvider` behind a `BillingProvider` seam (mirror `AI_PROVIDER_MODE`):
  a checkout/subscription-create flow and a webhook endpoint that syncs subscription
  status → `organizations.plan_key` (+ a `subscription_status` column). **No card data in
  our DB** — store only Stripe customer/subscription ids. Webhook signature verified with
  `stripe_webhook_secret`.
- **Effort:** ~1 focused slice once the key exists.

## 2. Execution-driven self-repair (C3, deep) — *architectural*

- **State:** `render.py` ships the *structural* self-repair (Loop 0) — one bounded retry
  when a render isn't a valid test class (ADR-0070). The high-value repair — fixing bad
  *assertions/setup* that ERROR at **execution** — is not built.
- **Why deferred:** it couples the currently-separate generation and execution phases
  (generate → execute pre-flight → feed the error back → regenerate), and validating it
  needs the heavy runner lane (`make test-runners` / `test-e2e-runner`), not the fast suite.
- **To land:** either interleave gen/exec per test, or a post-execution pass that
  regenerates ERROR'd AI cases (feeding the JUnit/stderr), marks `GenerationSignal.repaired`,
  and lets the fixed version run next time. Bounded retries. Test in the runner lane.

## 3. Cross-tenant flywheel learning (C4, cross-tenant) — *privacy-gated*

- **State:** `GenerationSignalRepository.good_exemplars` retrieves **same-project** proven
  tests as few-shot (ADR-0070). No cross-tenant sharing (the privacy landmine).
- **To land (opt-in only):** an org-level `share_anonymized_patterns` flag; an abstraction
  layer that strips a tenant's source/strings down to route-shape + assertion idiom (never
  raw code); optional aggregation thresholds. Only then feed cross-tenant exemplars. This
  is both an ethics requirement and a sellable trust feature — do it carefully or not at all.

## 4. Impersonation UI banner (A12 UX) — *small*

- **State:** the backend marks impersonation sessions (`sessions.impersonated_by`, ADR-0071)
  and audits them; there is no visual indicator.
- **To land:** surface an `impersonating: bool` (+ actor) on `GET /auth/me` from the session
  record, and render a persistent banner in `AppShell` while impersonating, with a
  "stop impersonating" action (drop the token). Low effort, high safety/clarity value.

## 5. SSO / SAML (enterprise) — *not started*

- Listed in the Business/Enterprise plan `features` (ADR-0069) but unimplemented. Needs a
  pluggable `AuthStrategy` extension (there is already an interim OTP strategy seam) +
  per-org IdP config. Enterprise-gated; sales-led.

## 6. Smaller polish noted in passing

- **Admin filter values:** the admin Incidents/Audit filters self-populate from values seen
  while paging (there's no distinct-values endpoint). A `GET /admin/audit/actions` (and an
  incidents-phases) endpoint would make the filters exhaustive.
- **Richer metering:** run-credits are 1-per-run today; the ADR-0069 plan was cost-∝-credit
  (size the debit by the real per-run AI cost we already capture, ADR-0049) — a margin-tuning
  refinement, additive to `app/api/quota.py`.
- **`exhaustive-deps` warnings:** two pre-existing eslint warnings on `refreshNonce` in the
  admin list pages (a deliberate reload nonce) — harmless; tidy if they bother anyone.
