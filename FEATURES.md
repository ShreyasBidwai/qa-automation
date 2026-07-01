<div align="center">

# ✨ Polaris — Feature Guide

### The autonomous QA platform that reads your app, writes the tests, runs them, and hands you *findings* — not noise.

![make test](https://img.shields.io/badge/make%20test-passing-2ea44f?style=for-the-badge)
![backend](https://img.shields.io/badge/backend-837%20passed-2ea44f?style=flat-square)
![frontend](https://img.shields.io/badge/frontend-191%20passed-2ea44f?style=flat-square)
![e2e](https://img.shields.io/badge/e2e-1%20passed-2ea44f?style=flat-square)
![stubs](https://img.shields.io/badge/boots%20with-zero%20credentials-4f46e5?style=flat-square)

*Everything in this document is **implemented, tested, and on trunk right now.***

</div>

---

## 🧭 How to read this guide

Polaris is built on a simple principle: **every capability has a real implementation *and* a safe fallback.** A fresh clone boots with **zero credentials** — the whole product is clickable with demo data — and each feature "lights up" for real the moment you provide its key or toolchain.

| Legend | Meaning |
| :---: | --- |
| 🟢 **Real** | The production implementation — the actual model, browser, or storage. |
| ⚪ **Fallback** | The safe default when the real path isn't configured. Nothing is ever hard-blocked. |
| 🔑 | Needs a secret (an API key or an encryption key) — always **env-only**, never in code or the DB. |
| 🧰 | Needs a toolchain present (a runner image, a browser, a Node driver). |

> [!TIP]
> Out of the box, every seam runs in **stub** mode, so you can walk the entire product end-to-end with `make seed-demo` before wiring anything up. Flip one env var per feature to go live.

### Contents
1. [🚀 What you do, start to finish](#-what-you-do-start-to-finish)
2. [⚙️ The run pipeline](#️-the-run-pipeline)
3. [🤖 The AI layer (fully provider-agnostic)](#-the-ai-layer--fully-provider-agnostic)
4. [🌐 The live crawl (stack-agnostic)](#-the-live-crawl--stack-agnostic)
5. [🔐 Storage, platform & security](#-storage-platform--security)
6. [🎛️ Flip stub → real (env reference)](#️-flip-stub--real)
7. [⚠️ Honest caveats](#️-honest-caveats)

---

## 🚀 What you do, start to finish

<div align="center">

```
  Sign up ──▶ Create project ──▶ Pick AI + set login ──▶ Start run ──▶ Watch it live
   (team)      (repo + URL)      (provider + account)     (one click)   (browser window!)
```

</div>

1. **Sign up**, create an organization, invite your team (role-based access).
2. **Create a project** — repo URL + the running app URL.
3. In settings: choose your **AI provider** (Anthropic / Gemini / Claude CLI), store the **target account** (password + optional TOTP), and the **login page** config.
4. **Start a run** and land on the **live view** — watch Polaris:
   > **ingest → generate tests → execute → crawl the site live (logging in, clicking through) → assemble findings**, each **AI-triaged** (real bug vs. noise), with failures captured as **screenshots**.

---

## ⚙️ The run pipeline

*Ingest → Brain → Generate → Execute → Findings. One run covers backend + DB + frontend.*

| Capability | What you can do right now | 🟢 Real tool | ⚪ Fallback |
| --- | --- | --- | --- |
| **Ingest a codebase → the Brain** | Point at a Laravel repo; get a graph of routes / models / migrations | Laravel **static source parser** — reads source, never boots the app (ADR‑0055) 🧰 | `stub` ingestor (canned graph, no target) |
| **Semantic Brain + retrieval** | Ground generation in the *right* nodes, not a repo dump | **fastembed** local ONNX `BAAI/bge-small-en-v1.5` + **pgvector** | `stub` embeddings (deterministic, no download) |
| **Generate runnable tests** | Author PHPUnit/Pest tests that run under both | **AI provider** — frontier model `claude-opus-4-8` 🔑 | `stub` provider (deterministic canned test) |
| **Execute against a throwaway DB** | Run the tests, dual‑DB safe (never touches prod) | **Pest / PHPUnit** runner + JUnit parsing 🧰 | `stub` executor (canned pass/fail) |
| **Assemble findings** | Root‑cause keying, severity, new/regression/flaky/known history, honest self‑healing | Deterministic engine — **no AI, always on** | *n/a* |

---

## 🤖 The AI layer — *fully provider-agnostic*

> [!IMPORTANT]
> **Add a provider and its key, and it just works** — per project, no code change, for **both** generation and triage. Keys are env-only and travel in HTTP **headers**, never URLs or logs.

| Feature | What you can do right now | 🟢 Real tool | ⚪ Fallback |
| --- | --- | --- | --- |
| **Generation** | Author tests with a frontier model | `anthropic_api` (Claude Messages API) · `claude_cli` (`claude -p`) · `gemini` — **chosen per project in the UI** 🔑 | `stub`; **plus** Gemini's rate‑limit‑aware **model‑fallback chain**, and a host **bridge** for the CLI |
| **AI‑driven triage** | Classify each failure — **real‑bug / bad‑test / flaky / infra** | Same provider's **cheap tier** `claude-haiku-4-5` (or `gemini-2.5-flash`) 🔑 | `stub` keyword heuristic; a triage error → label blank, **run continues** (best‑effort) |
| **Cost & usage capture** | See real billed tokens / $ per run (ADR‑0049) | Parses the provider's usage envelope | Flagged "unavailable"; run unaffected |
| **Agnostic key handling** | Anthropic **or** Gemini, each reading its own key | `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` — header‑delivered, never logged 🔑 | Missing key → **fails fast** with a clear error (never calls unauthenticated) |

<div align="center">

**Model tiers** — `generate: claude-opus-4-8` *(frontier)*  ·  `triage: claude-haiku-4-5` *(cheap)*  ·  `gemini-2.5-flash` — all config-driven.

</div>

---

## 🌐 The live crawl — *stack-agnostic*

> The crawler drives the **rendered** app, so it works on **any** stack — Laravel, React, Vue, whatever ships to the browser.

| Feature | What you can do right now | 🟢 Real tool | ⚪ Fallback |
| --- | --- | --- | --- |
| **Crawl the live site** | BFS‑crawl a running app; discover pages **and the backend endpoints each page calls** | **Playwright / chromium** (`crawl_page.mjs`) 🧰 | Skipped if no driver dir; injectable fake in tests |
| **👀 Watch it live** | See a real **browser window** in the Polaris UI advancing page‑by‑page — you land on it the instant a run starts | SSE progress stream + per‑step **screenshot frames** | Honest "frame unavailable" placeholder |
| **Log in + crawl behind the gate** | Configure a login URL + account; Polaris signs in and crawls gated journeys | Playwright **login driver** (`auth_login.mjs`) + AuthStrategy 🧰🔑 | Unauthenticated crawl if no login config |
| **Unattended 2FA** | Store a TOTP seed → runs generate the 6‑digit code and log in **with no human** | **pyotp** (RFC 6238) `TotpStrategy` 🔑 | Manual‑OTP (human types code); email/SMS OTP parked |
| **Interaction crawling** | Deeper coverage — clicks safe controls (tabs, filters, "load more") to surface click‑triggered endpoints | Playwright, **denylist‑guarded** — never submits a form or fires a destructive action | Toggle off → passive crawl |
| **Per‑project screenshots** | Every project's frames kept together; served only through the authorized endpoint | Local disk **or** any **S3** bucket | — |

---

## 🔐 Storage, platform & security

| Feature | What you can do right now | 🟢 Real tool | ⚪ Fallback |
| --- | --- | --- | --- |
| **Screenshot / evidence storage** | Run **decoupled** (runner ≠ control plane) and screenshots still serve across containers | **S3‑compatible object storage** — boto3 (AWS S3 / MinIO / any S3 API) 🔑 | Local disk (default, single‑box) |
| **Accounts & teams** | Sign up, orgs, role‑based access (owner / admin / member / viewer) | Argon2id passwords, opaque server sessions | — |
| **Target‑account vault** | Store a QA account's password **+ TOTP seed**, encrypted at rest, **write‑only** | **Fernet** encryption 🔑 (`TARGET_CREDENTIALS_KEY`) | No key → write **refuses** (never stores plaintext) |
| **Auth‑config from the UI** | Set login URL + selectors + TOTP entirely in project settings — no secret in the endpoint | REST endpoint + React form | — |
| **Durable runs** | Queue runs, survive restarts, drain to decoupled workers | **Postgres** job queue (`FOR UPDATE SKIP LOCKED`) — no Redis | — |
| **DB‑state testing** | Assert real database state changes (tier‑gated per project) | Introspection against the throwaway test DB | Off by default (no‑op) |
| **Document upload** | Upload business docs → spec‑grounded oracles | pgvector‑embedded documents | `stub` embeddings |

> [!NOTE]
> **Security posture, everywhere:** secrets are env/vault‑only, sent via headers (never URLs), repr‑masked, and never logged, returned in a payload, or written to the DB in the clear. The runner writes only to a **throwaway** test DB (dual‑DB guard). Polaris **never targets production.**

---

## 🎛️ Flip stub → real

<details>
<summary><b>One env var per feature — click to expand the full reference</b></summary>

| Feature | Env | Real value | Also set |
| --- | --- | --- | --- |
| **Ingestion** | `INGESTOR_MODE` | `laravel` | a Laravel repo/checkout |
| **Execution** | `EXECUTOR_MODE` | `orchestrator` | the Pest/Playwright runner image |
| **Embeddings** | `EMBEDDING_PROVIDER` | `local` | *(downloads the fastembed model)* |
| **AI provider (instance default)** | `AI_PROVIDER_MODE` | `anthropic_api` \| `gemini` \| `claude_cli` | the matching key below |
| **Anthropic** | `ANTHROPIC_API_KEY` 🔑 | *your key* | uses `ai_generate_model` + `ai_triage_model` |
| **Gemini** | `GEMINI_API_KEY` 🔑 | *your key* | optional `GEMINI_MODEL_CHAIN` fallback |
| **Frontend crawl** | `CRAWL_DRIVER_DIR` | *path to the Playwright driver* | chromium present |
| **Interaction depth** | `CRAWL_INTERACTIONS_ENABLED` | `true` *(default)* | `CRAWL_MAX_INTERACTIONS` |
| **Screenshots at scale** | `SCREENSHOT_STORAGE` | `s3` | `SCREENSHOT_S3_BUCKET` + AWS env creds |
| **Credential vault** | `TARGET_CREDENTIALS_KEY` 🔑 | *a Fernet key* | enables the account/TOTP vault |

> Per‑project overrides (AI provider, login config, TOTP, DB‑state tier) are set **in the UI** and take precedence over the instance defaults above.

</details>

---

## ⚠️ Honest caveats

So *"right now"* stays accurate:

- **Ingestion is Laravel‑only** for real targets today (other stacks fall back to the stub) — **but the crawler is stack‑agnostic** and works on any rendered app.
- **Real generation / execution / crawl need their toolchains present** (an AI key, the Pest/Playwright runner). Without them, every seam degrades to its stub — so the product still runs **end‑to‑end**, just with fakes instead of a real model or browser.
- **Email / SMS OTP** auth strategies are declared but **parked** (TOTP is real); they unpark when the challenge log shows they dominate.

---

<div align="center">

*Built to be watched. Every run is a browser window you can see — logging in, clicking through, catching bugs.*

**🤖 Generated with [Claude Code](https://claude.com/claude-code)**

</div>
