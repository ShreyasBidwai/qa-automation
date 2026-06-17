# laravel-app — bootable target-under-test fixture

A minimal but **complete, runnable** Laravel 11 app used as the offline target
for the Pest runner integration tests (T1.5). It extends the T1.3 snippet
fixture (`../laravel/`) into something that actually boots, migrates, and
serves requests so the `PestRunner` can execute real Pest feature tests against
it.

## What it contains

- `User` + `Country` Eloquent models and their migrations (`country_id`
  satisfies the `exists:countries,id` rule).
- `UserController@store` validated by the type-hinted `StoreUserRequest` — the
  **same validation shape** the T1.3 extractor reads, so the PHP-helper
  integration test pins the real `extract_validation.php` output against the
  Python normalizer.
- `routes/web.php` — `POST /users` behind the `auth` middleware (401 when
  unauthenticated; `actingAs()` in tests authenticates).
- `DatabaseSeeder` — the baseline the generated plan's db-dependencies need: one
  `Country` (id 1) for a valid `exists` reference and one `User` with a known
  email (`existing@example.com`) for the `unique` duplicate case. Re-seeded
  before every test via `RefreshDatabase` + `TestCase::$seed`.

## Database

Feature tests run against an **in-memory sqlite** DB (`phpunit.xml`), migrated
fresh per test. This is the writable, ephemeral test DB the runner targets — it
dies with the Pest process, so there is nothing to leak (Architecture §9,
Standards §11). Execution never touches a real/read-only DB.

## Running

Only inside the `runners/laravel` image (PHP + Composer + Pest are not in the
fast backend env):

```bash
make test-runners
```

`vendor/` is produced by `composer install` at image build time and is
git-ignored. `nikic/php-parser` is a runtime dependency so the same image can
exercise the T1.3 `extract_validation.php` helper against this app.
