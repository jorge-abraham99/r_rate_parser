# Supabase Migration Baseline

Stage 0 was captured on 8 August 2026 from the existing hosted project. It did not apply SQL or otherwise mutate the remote database.

## Linked project

- Project: `carrier-quotes`
- Project reference: `vwwnnvdusutyucsnndyc`
- Region: `eu-west-1`
- PostgreSQL: `17.6`
- Local configuration: `supabase/config.toml`

The generated configuration targets PostgreSQL major version 17. Local Supabase commands require Docker, which is not currently installed on the development machine.

## Authoritative remote migrations

The following versions were already present in `supabase_migrations.schema_migrations`. Their stored SQL was copied exactly and verified using normalized MD5 hashes:

| Version | Name | Normalized MD5 |
| --- | --- | --- |
| `20260807222346` | `initial_rate_library_schema` | `bc60ae1d07d20529a02e33f9153274fd` |
| `20260807222404` | `add_missing_fk_indexes` | `e312e0eef3c5477a1b9ab7651d85fdb1` |

These migrations are already applied remotely. Do not push or replay them against `carrier-quotes`. They are the baseline for new environments and for future additive migrations.

## Captured schema

The public schema contains eight tables:

- `organizations`
- `organization_members`
- `source_documents`
- `rate_imports`
- `rate_cards`
- `rate_offers`
- `rate_charge_lines`
- `rate_notes`

All eight tables have RLS enabled. The captured grants and policies provide:

- no table access to `anon`;
- membership-scoped reads for `authenticated`;
- organization-scoped writes for authenticated `admin` and `operator` members on rate data;
- full table privileges for `service_role`.

The public schema has no custom functions, triggers, views, materialized views, enums, or domains. The baseline includes all observed primary keys, unique constraints, checks, foreign keys, 22 non-constraint indexes, grants, and 26 RLS policies.

The Supabase Security Advisor reported zero findings at capture time. The Performance Advisor reported 22 informational `unused_index` findings, expected because the project was newly created and had not served application traffic. No indexes were removed.

## Stage 4 additive migration

Migration `20260808150650_add_application_ids.sql` was applied to the hosted project on 9 August 2026. It adds `application_id text` to:

- `source_documents`
- `rate_imports`
- `rate_cards`
- `rate_offers`
- `rate_charge_lines`
- `rate_notes`

Each new value is non-empty and unique within one organization. Existing rows receive a deterministic value based on their UUID before the columns become `NOT NULL`. Database foreign keys remain UUID-based; repository adapters translate between UUID primary keys and application-facing string IDs.

The post-migration Supabase security and performance advisor check reported no warning- or error-level issues. The guarded Hapag integration test passed and verified source deduplication, cross-organization checksum reuse, entity counts, application-ID round trips, and organization isolation. Run the test only with disposable data:

```bash
RUN_POSTGRES_INTEGRATION_TESTS=true pytest -q tests/test_postgres_repository_integration.py
```

The test creates two unique temporary organizations and deletes only those organization IDs in cleanup.

The committed migration file SHA-256 is `6c69c57abdda4a25785a84fda7b0475fcacbb912ffcbb4198448748e9b176715`.

Production remains on `RATE_STORAGE_BACKEND=csv`. Stage 5 lifecycle ownership is complete; Stage 6 will move Import UI and Rate Desk reads before the production cutover.

## Stage 5 lifecycle migration

Migration `20260809210000_allow_signed_charge_amounts.sql` was applied on 9 August 2026. It removes the non-negative check from charge-line amounts. Existing parsers use signed charge values for discounts and freight adjustments, so Postgres must preserve those values. Offer base amounts remain non-negative.

Stage 5 persists cards, offers, charge lines, and notes before review. Approval and same-carrier archive run in one transaction. Archived and rejected rows remain in Postgres. Deleting an import cascades to parsed children but does not delete its source document.

The remote migration list matches all four local migrations, and the post-migration public-schema lint reports no errors. Guarded tests compare real CSV parser output with Postgres for all nine parser families. The tests create unique temporary organizations and remove only those exact IDs during cleanup.

Production remains on `RATE_STORAGE_BACKEND=csv` until Stage 6 moves Import UI and Rate Desk reads.

## Stage 1 and Stage 2 authentication status

The FastAPI backend validates Supabase user access tokens through the project's public ES256 JWKS. It then reads `organization_members` through the Data API with the same user token. Existing RLS limits the result to the signed-in user. `GET /api/me` returns the verified user and memberships.

The verifier checks the signature, exact issuer, `authenticated` audience, expiry, UUID subject, and authenticated role. It does not use the JWT signing secret or a service-role key. JWKS data is cached for no more than 10 minutes.

Stage 2 protects imports, search, and Rate Desk. Viewer, operator, and admin roles can read. Only operator and admin roles can mutate. Health, public browser configuration, and static files remain public. The same-origin application has no CORS middleware. `AUTH_REQUIRED` defaults to `true`.

The static browser UI uses pinned `@supabase/supabase-js` `2.112.2` with a SHA-384 integrity value. It supports email/password login, session restoration, token refresh, local logout, and one shared authenticated API helper. It has no public sign-up action.

Before deployment, confirm that email/password login is enabled, public sign-up is disabled, the Site URL and redirect URLs are correct, and each invited user has an `organization_members` row.

## Stage 6 and Stage 7 trial cutover

Stage 6 makes Import review and Rate Desk reads use the selected repository backend. Stage 7 adds `UI/set-password.html`, which accepts a Supabase invitation session, updates the password through the browser client, checks `GET /api/me`, and only then sends an authorized user to the Rate Desk.

For Dashboard-sent invitations, set the Site URL to the password page because the Dashboard does not supply a custom `redirectTo`. Allow both the normal application root and the exact password page:

```text
Site URL: https://rrateparser-production.up.railway.app/ui/set-password.html
Redirect URL: https://rrateparser-production.up.railway.app/
Redirect URL: https://rrateparser-production.up.railway.app/ui/set-password.html
```

Keep public sign-up disabled. Invite the user, add their resulting `auth.users.id` to the intended `organization_members` row, and assign `viewer`, `operator`, or `admin` deliberately. The browser page contains no service-role key or database credential.

The current trial intentionally starts with an empty Postgres rate library. Do not run a backfill before changing Railway to `RATE_STORAGE_BACKEND=postgres`; CSV rates remain available only through a rollback to `RATE_STORAGE_BACKEND=csv`.

The following optional command is retained for a later recovery/migration decision:

```bash
python -m rate_ingest backfill-postgres <organization-uuid>
python -m rate_ingest backfill-postgres <organization-uuid> --apply
```

The dry run verifies that every CSV import has a source file and structured run bundle. The applied run upserts the same application IDs into the given organization and can be retried. It is not dual-write: imports created in Postgres after cutover are absent from the CSV rollback store.

## Credentials

Copy `.env.example` to `.env` for local work. `.env` is ignored by Git.

- `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are used by the authenticated client and membership flow.
- `SUPABASE_DB_URL` is server-only and must never be exposed to browser code.
- `SUPABASE_DB_URL` must require SSL. Use a direct connection or the session pooler for this persistent FastAPI service.
- `SUPABASE_ACCESS_TOKEN` is local migration tooling only and must never be committed.

Do not add a Supabase secret/service-role key to frontend configuration.
