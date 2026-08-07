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

## Required first additive migration

The running application exposes string IDs such as `import_...`, `card_...`, and `offer_...`, while the captured database uses UUID primary keys. Before PostgreSQL becomes the runtime source of truth, add `application_id text` to:

- `source_documents`
- `rate_imports`
- `rate_cards`
- `rate_offers`
- `rate_charge_lines`
- `rate_notes`

Use organization-scoped uniqueness where appropriate. Database foreign keys remain UUID-based; repository adapters translate between UUID primary keys and application-facing string IDs. This must be an additive migration after the current model and relationship mapping is verified, not a broad rewrite of API IDs.

## Credentials

Copy `.env.example` to `.env` for local work. `.env` is ignored by Git.

- `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are used by the future authenticated client flow.
- `SUPABASE_DB_URL` is server-only and must never be exposed to browser code.
- `SUPABASE_ACCESS_TOKEN` is local migration tooling only and must never be committed.

Do not add a Supabase secret/service-role key to frontend configuration.
