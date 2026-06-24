# ADR-0055: Laravel ingestion is static source reading (the app is never booted)

- Status: Accepted
- Date: 2026-06-24
- Deciders: Engineering

## Context

Ingestion's job is to **read the target codebase** and build the Brain
(model_nodes / model_edges — the understanding/connections the rest of Polaris
queries). The Laravel ingestor did the opposite: it **booted the target app** to
discover the graph.

- Routes came from `php artisan route:list --json` — which boots the whole
  framework: `.env`, a reachable database, every service-provider credential, and
  every route's controller class resolving.
- Models / migrations / controllers came from a PHP AST helper
  (`php/extract_graph.php`) that requires the target's `vendor/autoload.php` +
  `nikic/php-parser`, i.e. a successful `composer install`.

This made ingestion depend on the target being **runnable**, not merely
**readable**. The real failure that surfaced it: one route referenced a controller
class that did not resolve, so `artisan route:list` exited non-zero and **aborted
the entire ingestion** — no Brain at all from an otherwise-readable repo. It also
makes ingestion non-portable (needs PHP, Composer, a DB, valid config) and
project-specific.

## Decision

**Ingestion reads source only. The sole thing required from the target is the
repo.** No artisan, no PHP, no `vendor/`, no DB, no config, no running app. This is
project-agnostic and is the default and only *required* path.

### Static parsers are the guaranteed baseline

Two pure-Python parsers replace the two app-execution calls. They produce the
**exact same fact shapes** the ingester already consumes (`RouteFacts`,
`RepoGraph`/`ModelMeta`/`MigrationMeta`/`ActionMeta`/`Relationship`/
`ActionValidation`), so the downstream node/edge build is unchanged.

- `app/ingestion/laravel/static_routes.py` — parses `routes/*.php` with a
  string/comment-aware brace scanner (no PHP, no AST): the verb calls
  (`get/post/put/patch/delete/options/any`, `match([...])`), `resource` /
  `apiResource` (expanded to the REST sub-routes), and groups — `prefix` / `name`
  (`as`) / `middleware` / `controller`, the array form `Route::group([...], fn)`,
  and nesting. Controller references resolve to an FQCN via the file's `use`
  imports (and the `App\Http\Controllers` default namespace, as Laravel's PSR-4
  does). `routes/api*.php` gets the conventional `api` prefix + middleware.
- `app/ingestion/laravel/static_graph.py` — parses models (`$table` or
  pluralise(snake(class)), `$fillable`, declared `$this->belongsTo(...)` etc.
  relationships), migrations (`Schema::create('t', fn($t){…})` columns, including
  `id`/`timestamps`/`softDeletes`/`rememberToken`), and controllers (public
  actions, statically-referenced models, and validation — a type-hinted
  FormRequest's `rules()` keys or an inline `$request->validate([...])`).

### Robustness is a first-class requirement, not a nicety

Real apps are messy. Malformed or broken source must **never abort ingestion**:
every file is parsed defensively (per-file try/except), and the unit of failure is
one file or one statement, never the run. A route whose controller can't be turned
into a class (a bare action with no controller group, a `$variable` controller) is
**recorded** in `StaticRoutes.unresolved` and the route is still emitted; a broken
migration / odd class / `_original` duplicate is skipped and logged. "Parse what's
parseable, record what isn't, keep going." The static parser **cannot** crash the
way `artisan route:list` did, because it never loads a class — it only reads text.

### Runtime `artisan route:list` is optional, off-by-default, fully fail-safe

Dynamic/package-registered routes (those a static read can't see) remain
recoverable as **additive enrichment**, never a dependency:

- `LaravelIngester(enrich_with_artisan=False)` by default — the static baseline is
  the whole story.
- When explicitly enabled **and** the target happens to boot, artisan-discovered
  routes are merged into the static set, **de-duplicated** by `(method, uri)`.
- **Any** error (non-zero exit, no DB, no vendor, bad JSON, timeout) is swallowed
  and the static results stand. Enrichment can add, never subtract, never block.

"Static = guaranteed baseline that always works; runtime = optional additive
completeness when available."

### The commit SHA is best-effort

`source_sha` (the Brain's change-invalidation carrier, ADR-0010) is supplied by the
caller when a checkout already resolved it (`ingest_from_git`). Otherwise the
ingester tries `git rev-parse HEAD` **best-effort** — a missing git or non-repo
path falls back to a `"static-ingest"` marker rather than failing. Git is never
required for ingestion.

## Consequences

- **Project-agnostic and portable.** Ingestion needs only a readable repo — it runs
  in the slim runtime image with just Postgres (for node storage). No PHP, no
  Composer/`vendor`, no target DB or config. A broken target app still yields a full
  Brain.
- **Proven against a real, messy app.** Static-ingesting the production Laravel
  target (`/targets/app`: 5 route files, hundreds of models/controllers, **774
  migrations**, `vendor/` present but never read) with a CommandRunner that *raises
  on any subprocess* (so a boot would fail the test) built the Brain in ~12s with
  **no boot / DB / config / vendor**: **1651 model_nodes** (185 tables, 231 models,
  1235 endpoints) and **2773 model_edges**, parsing every file without a crash.
- **Downstream unchanged.** The fact shapes match exactly, so node/edge
  construction, embeddings, the SHA-keyed embed cache, the resolver, and git-driven
  ingestion are untouched (their tests now build the Brain from real fixture
  *source* instead of canned `artisan`/AST JSON, asserting the same nodes/edges).
- The PHP helpers (`php/extract_graph.php`, `php/extract_validation.php`) remain in
  the tree: `extract_graph.php` is no longer on the ingestion path; the
  generation-time validation extractor is a separate concern (runs during a run,
  where the app is available) and is out of scope here.
