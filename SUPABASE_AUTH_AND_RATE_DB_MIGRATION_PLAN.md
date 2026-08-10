Reudan Rate Desk — Supabase Auth & Postgres Migration Plan

Status: Implementation handoffPrepared: 7 August 2026Supabase project: carrier-quotesSupabase project ref: vwwnnvdusutyucsnndyc

IMPORTANT — Supabase is already initialized.

The carrier-quotes Supabase project already exists and the production schema has already been created remotely. The following tables already exist in Supabase:

organizations

organization_members

source_documents

rate_imports

rate_cards

rate_offers

rate_charge_lines

rate_notes

RLS, grants, constraints, and the initial indexes have also already been applied, and the Supabase security advisor was clean after creation.

Agents must NOT recreate, drop, reset, or replace these remote tables. The first repository task is only to inspect the existing remote schema and capture it in source control/migrations so the codebase reflects what is already deployed.

Implementation reconciliation notes

Two current-repository facts override any conflicting examples elsewhere in this plan.

Current application IDs are strings

The current application uses human/application-style string identifiers such as:

offer_ab12...
import_...
card_...

These are not database UUIDs.

Do not silently replace the application's existing IDs with Postgres UUIDs in API responses, run artifacts, parser output, or cross-entity references.

The already-created Supabase tables currently use UUID primary keys. Therefore implementation should use a dual-ID strategy:

database id       uuid   -> internal Postgres primary key
application_id    text   -> existing application/parser identifier

Add an application_id text column to the relevant persisted entity tables before Postgres cutover, with an organization-scoped uniqueness constraint/index where appropriate.

At minimum reconcile this for:

source_documents

rate_imports

rate_cards

rate_offers

rate_charge_lines

rate_notes

The repository adapter owns translation between:

current Pydantic/string ID <-> Postgres UUID PK

The existing application-facing string ID remains authoritative for current API contracts and run artifacts during this migration.

Do not perform a broad application-ID rewrite as part of the database migration.

Current COSCO parser excludes non-priced tariff lines

The current COSCO PDF parser prices:

Freight Rate

EFS

collection IHL

It currently excludes documentation, destination handling, and the other non-priced tariff lines from parsed/persisted rate data.

Therefore this migration must preserve that behavior.

Any examples elsewhere in this document that show COSCO documentation or destination handling being stored/displayed but excluded from totals are future-state examples only, not current migration requirements.

For migration parity:

current parser output in CSV
==
current parser output in Postgres

Do not expand the COSCO parser's extracted charge coverage during the storage/auth migration.

Storing additional non-priced tariff lines may be considered later as a separate parser/product change with its own tests.

1. Goal

Move the existing Reudan freight-rate parser / Rate Desk from:

an unauthenticated public web application; and

CSV/JSON warehouse persistence on the Railway filesystem

to:

invite-only Supabase Auth;

authenticated FastAPI endpoints;

organization-scoped access;

Postgres persistence in Supabase;

the same parser, review, approval, and Rate Desk behavior the client already likes.

This is not a product rewrite.

The core rule for the migration is:

Do not change working parser behavior and infrastructure behavior at the same time.

The parsers are already trusted by the client. The migration should change authentication and persistence underneath the existing application while preserving its current output and UX.

2. Current application invariants

The current application is a single Python/FastAPI web process with a static HTML/JS frontend.

Important existing components:

rate_ingest/api.py — FastAPI routes, upload handling, health check, CORS, static UI.

rate_ingest/services.py — orchestration for import, review, approval/rejection, archive/delete, search, Rate Desk shaping, charge grouping, FX.

rate_ingest/models.py — Pydantic source/import/card/offer/charge/note models.

rate_ingest/source_registry.py — source registration + checksum deduplication.

rate_ingest/inspector.py — document inspection.

rate_ingest/template_matcher.py — deterministic template selection.

rate_ingest/parsers/ — deterministic carrier-specific parsers.

rate_ingest/validate.py — validation.

rate_ingest/review.py — review artifacts.

rate_ingest/approve.py — current publication behavior.

rate_ingest/warehouse.py — CSV warehouse persistence.

UI/import.html, UI/app.js — connected Import UI.

UI/index.html, UI/rate-desk.js — connected Rate Desk.

UI/config.js — runtime UI mode/configuration.

tests/test_rate_ingest_cli.py — current end-to-end coverage.

Current published data model:

SourceDocument

RateImport

RateCard

RateOffer

RateChargeLine

RateNote

The Postgres schema deliberately mirrors those concepts.

Non-negotiable behavior during migration

The following must remain stable unless a stage explicitly says otherwise:

Parser/template selection.

Carrier-specific pricing interpretation.

Validation results.

Review screen contents.

Existing import statuses:

pending_review

failed

approved

rejected

archived

Search/filter semantics.

Rate Desk calculation semantics.

Standalone haulage separation.

MSC/Hapag/COSCO/Maersk/CMA parser behavior.

Existing API response contracts unless a stage explicitly adds a new endpoint.

3. Target architecture

Browser
   |
   | Supabase Auth session
   v
Static Reudan UI
   |
   | Authorization: Bearer <access token>
   v
FastAPI
   |
   | verify JWT
   | resolve user + organization membership
   v
Application services
   |
   +------------------+
   |                  |
   v                  v
Parsers            Postgres
unchanged          Supabase
   |                  |
   v                  |
Review artifacts      |
                      |
                      v
                  Rate library

Supabase responsibilities:

Supabase Auth
    |
    v
auth.users
    |
    v
organization_members
    |
    v
organizations
    |
    +--> source_documents
    +--> rate_imports
    +--> rate_cards
    +--> rate_offers
    +--> rate_charge_lines
    +--> rate_notes

The browser may know:

Supabase project URL.

Supabase publishable key.

The browser must never know:

Postgres connection strings.

Supabase secret/service-role keys.

Any signing secret.

Railway server secrets.

4. Existing Supabase schema

The remote project already contains the following application tables.

organizations

Represents one customer/account.

Important columns:

id

name

slug

created_at

organization_members

Connects auth.users to an organization.

Important columns:

organization_id

user_id

role

created_at

Allowed roles:

admin

operator

viewer

Current intended meaning:

viewer — read/search only.

operator — may create/update/delete rate-library data.

admin — currently has the same data-write rights as operator; later can own user/org administration.

source_documents

Represents the source PDF/XLSX/CSV/EML uploaded by a user.

Important columns:

id

organization_id

original_filename

source_type

sha256

storage_path

uploaded_by

metadata

created_at

There is uniqueness on (organization_id, sha256).

rate_imports

Represents a parsing/import run for one source document.

Important columns:

id

organization_id

source_document_id

template_id

parser_family

match_confidence

status

carrier_key

validation_error_count

validation_warning_count

inspection

validation_report

parse_summary

approval/rejection/archive metadata

created_at

rate_cards

Represents document-level commercial metadata.

Important columns:

id

organization_id

import_id

provider

carrier

commodity

currency

valid_from

valid_to

is_all_in

document_type

contract_tag

metadata

created_at

rate_offers

Represents the searchable lane/equipment/service rows.

Important columns:

id

organization_id

import_id

rate_card_id

collection

origin

pol

pod

destination

equipment

service_mode

base_amount

currency

preferred_pol

routing

valid_from

valid_to

source_reference

metadata

created_at

rate_charge_lines

Represents individual pricing components.

Important columns:

id

organization_id

rate_card_id

rate_offer_id — nullable for card-level charges

charge_code

charge_name

amount

currency

basis

charge_type

is_included

source_reference

metadata

created_at

rate_notes

Represents non-numerical commercial/routing terms.

Important columns:

id

organization_id

rate_card_id

rate_offer_id — nullable

note_type

note_text

source_reference

metadata

created_at

All application tables have RLS enabled.

Anonymous users have no table access.

Authenticated users are restricted by organization membership.

Operators/admins may modify rate data; viewers may read it.

The Supabase security advisor was clean after schema creation.

5. Rollout strategy

This migration must be completed in small mergeable stages.

Every stage has four rules:

It must have a clearly bounded objective.

Existing tests must pass before moving on.

The app should remain runnable after the stage.

Commit the stage before beginning the next one.

Do not let an agent continue into the next stage just because it finished early.

At the end of every stage:

pytest -q
git diff --check
git status

Also manually run the FastAPI app and verify:

GET /api/health

Commit only after the stage-specific acceptance tests pass.

Suggested commit naming:

stage-0: capture supabase schema and migration config
stage-1: add supabase auth backend primitives
stage-2: add invite-only login flow and api auth
stage-3: introduce persistence repository abstraction
stage-4: add postgres rate repository
stage-5: persist imports and approval workflow in postgres
stage-6: read imports and rate desk from postgres
stage-7: cut over production persistence
stage-8: migrate raw sources to supabase storage
stage-9: post-trial hardening and pagination

STAGE 0 — Capture the remote schema in the repository

Objective

The Supabase project and application tables are already created remotely.

Stage 0 is not a schema-creation stage.

Its only purpose is to make the already-deployed Supabase schema reproducible and version controlled before changing application code.

No runtime behavior changes and no destructive remote database changes.

Tasks

Inspect and document the existing remote schema first.

Record the required additive ID reconciliation for implementation: the remote entity tables need an application_id text field before Postgres cutover because the running application uses string IDs. Do not apply this blindly in Stage 0; capture it as the first planned additive schema migration after repository/model mapping is verified.

Add a Supabase project directory/config if one does not already exist.

Link local Supabase tooling to:

project: carrier-quotes

project ref: vwwnnvdusutyucsnndyc

Capture the existing remote schema/migrations into the repository.

Do not recreate or drop the existing remote tables.

Ensure the checked-in SQL accurately represents:

the eight application tables;

constraints;

indexes;

grants;

RLS policies.

Document which migration represents the schema already applied remotely.

Use the current Supabase CLI help rather than guessing command syntax.

Important

The schema already exists remotely in Supabase, including the eight application tables, RLS policies, grants, constraints, and indexes.

The purpose of this stage is to put the existing database definition under source control, not to execute the initial schema again.

Do not run a reset, drop the schema, recreate the tables, or apply an "initial schema" migration against the remote project. Inspect/pull/capture what is there first.

Acceptance tests

Remote database remains unchanged.

Local migration/schema SQL exists in git.

pytest -q remains green.

git diff --check passes.

Stop here

Do not add auth or database runtime dependencies in Stage 0.

STAGE 1 — Add backend Supabase/Auth primitives without enforcing login

Objective

Teach the FastAPI application how to understand a Supabase user token while leaving all current routes operational.

This stage should not lock anyone out.

Likely files

Create:

rate_ingest/auth.py

Potentially create:

rate_ingest/database.py

Modify:

rate_ingest/config.py
rate_ingest/api.py
requirements.txt
pyproject.toml

Keep requirements.txt and pyproject.toml synchronized.

Configuration

Add server-side configuration for values such as:

SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
SUPABASE_DB_URL

AUTH_REQUIRED=false

Names may be adjusted to match the existing Settings style.

SUPABASE_DB_URL is secret and server-only.

Do not require a service-role key merely to make this stage work.

JWT validation

Create an authentication dependency/service which:

Reads Authorization: Bearer <token>.

Validates the token was issued by the configured Supabase project.

Validates:

signature;

issuer;

audience;

expiration.

Extracts the Supabase sub user UUID.

Rejects malformed/expired tokens.

Preferred implementation:

detect/use Supabase asymmetric signing keys;

validate via the project's JWKS endpoint using a maintained Python JWT library.

If the project is still using HS256:

do not copy the Supabase JWT signing secret into application code;

use the Auth server's user validation endpoint or move the project to asymmetric signing before relying on local verification.

Do not implement JWT crypto manually.

Add an authenticated diagnostic endpoint

Example:

GET /api/me

Response should eventually contain something like:

{
  "user_id": "...",
  "email": "...",
  "organizations": [
    {
      "id": "...",
      "name": "Reudan",
      "role": "operator"
    }
  ]
}

For Stage 1, /api/me may be the only route requiring authentication.

Existing Rate Desk/import routes remain unchanged while:

AUTH_REQUIRED=false

Tests

Add tests for:

missing Authorization header;

malformed header;

invalid JWT;

expired JWT;

valid JWT;

/api/me requires authentication.

JWT verification should be mockable so the normal test suite does not depend on live Supabase.

Acceptance tests

Existing 15+ tests remain green.

/api/health works without auth.

Existing UI still works exactly as before.

/api/me returns 401 without a token.

/api/me works with a valid test token/mocked verifier.

Stop here

Do not build the login UI yet.

Do not change warehouse persistence yet.

STAGE 2 — Add invite-only login and protect the application

Objective

When a user visits the Rate Desk URL they should see a login screen, not rate data.

All sensitive FastAPI endpoints must reject unauthenticated requests.

Supabase dashboard setup before code cutover

Confirm:

Email/password authentication is enabled.

Public/open signup is disabled.

Users will be created/invited deliberately.

Correct Site URL is configured.

Correct redirect URLs are configured.

At least one real trial user exists.

The user has an organization_members row for the Reudan organization.

Do not use user_metadata as the authorization source.

organization_members is the source of truth.

Frontend changes

Because the application currently has static HTML/JS and no frontend build service, avoid introducing a full JS framework.

Possible files:

UI/login.html
UI/auth.js
UI/config.js
UI/app.js
UI/rate-desk.js

Use a pinned Supabase JS version if loading it directly in the browser.

Never use an unversioned latest package URL.

Public runtime configuration

The frontend needs only public values:

SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY

Prefer serving these from a small endpoint such as:

GET /api/public-config

rather than committing deployment-specific config into source files.

That endpoint must return only values intentionally safe for browser exposure.

Login behavior

Implement:

sign in with email + password;

session restoration after refresh;

logout;

expired-session handling;

redirect to/login gate when unauthenticated.

For the trial, do not add a public Create Account button.

Authenticated API wrapper

Create one shared frontend helper for API calls.

It should:

obtain the current Supabase access token;

attach:

Authorization: Bearer <access_token>

call FastAPI;

handle 401 by returning the user to login;

handle 403 as "signed in but not authorized".

Do not manually duplicate token attachment logic in every fetch call.

Refactor existing UI/app.js and UI/rate-desk.js requests through this wrapper.

Protect FastAPI routes

Auth should be required for:

GET    /api/imports
POST   /api/imports
GET    /api/imports/{id}
POST   /api/imports/{id}/approve
POST   /api/imports/{id}/reject
DELETE /api/imports/{id}
GET    /api/search
GET    /api/rate-desk

Leave these public:

GET /
GET /api/health
GET /api/public-config

Static assets may remain publicly downloadable.

That is not a data leak.

The important rule is:

Loading the HTML/JS without a session must never reveal rate data or allow the protected APIs to be called.

Membership authorization

After JWT authentication, resolve the user through organization_members.

For the first trial there may only be one organization, but do not hard-code "all authenticated users belong to Reudan".

Request context should expose:

user_id
organization_id
organization_role

If the user has no active organization membership:

403 Forbidden

Roles

At minimum:

viewer:
  search/read Rate Desk
  view imports/reviews

operator/admin:
  everything viewer can do
  upload
  approve
  reject
  archive/delete

Apply role checks in FastAPI even though RLS also exists.

CORS

The current application allows all origins/methods/headers.

Change this.

If UI and FastAPI are served from the same domain:

CORS may be removable entirely.

If cross-origin access is needed:

allow only the real trial/production origins;

never retain *.

Tests

Backend:

no token => 401 on every protected API;

invalid token => 401;

valid user without membership => 403;

viewer can read;

viewer cannot mutate;

operator can read + mutate;

admin can read + mutate;

/api/health remains public.

Frontend/manual:

visiting URL while logged out shows login;

refresh while logged in preserves session;

logout removes access;

direct /api/rate-desk call without JWT receives 401.

Acceptance gate

Do not move to database migration until the application can be safely given to a client user with authentication enabled.

Stop here

The system should still be using the existing CSV warehouse.

This is an intentional stable checkpoint.

STAGE 3 — Introduce a persistence/repository abstraction with CSV still active

Implementation status: complete on 8 August 2026. `RateRepository` and `CsvRateRepository` now cover source registration, import records, approval publication, removal, and approved-library reads. `RATE_STORAGE_BACKEND=csv` remains the default. At this checkpoint, the `postgres` value was reserved until Stage 4. Existing run artifacts and API/UI contracts were unchanged.

Objective

Separate business logic in services.py from the implementation details in warehouse.py.

No database cutover yet.

This is the most important "make later stages safe" refactor.

Why

Currently service behavior is tightly coupled to CSV/JSON functions.

We want:

services.py
   |
   v
RateRepository interface
   |
   +--> CsvRateRepository
   |
   +--> PostgresRateRepository

Then switching storage becomes configuration rather than a rewrite of parser logic.

Suggested structure

Possible new package:

rate_ingest/repositories/
    __init__.py
    base.py
    csv_repository.py
    postgres_repository.py   # may remain placeholder in this stage

Alternative names are fine if consistent with the repo.

Repository responsibilities

The interface should cover business persistence operations rather than raw SQL-shaped methods.

Examples:

register_source_document(...)
save_import_bundle(...)
get_import(...)
list_imports(...)
approve_import(...)
reject_import(...)
archive_import(...)
delete_import(...)
search_approved_offers(...)
load_rate_desk_data(...)

Do not over-generalize into a generic ORM abstraction.

The repository API should reflect how this application actually uses its data.

CSV adapter

Wrap the current:

source_registry.py
warehouse.py
approve.py

behavior behind the new repository interface.

Do not delete the existing implementation yet.

Feature/config flag

Add something like:

RATE_STORAGE_BACKEND=csv

Allowed future values:

csv
postgres

For Stage 3, default must remain:

csv

Critical acceptance test

With RATE_STORAGE_BACKEND=csv:

all existing tests should continue to pass with equivalent behavior;

no UI behavior should change;

generated run artifacts should remain identical;

search should return the same results;

approval/replacement behavior should remain the same.

Stop here

Do not add Postgres writes until the CSV adapter is proven.

STAGE 4 — Implement PostgresRateRepository without production cutover

Implementation status: complete on 9 August 2026. The Postgres adapter, explicit mappings, SSL connection pool, organization-scoped operations, bulk writes, and application-ID migration are present. Migration `20260808150650_add_application_ids` is applied remotely. The guarded real Hapag test passed its entity-count, application-ID, checksum, cleanup, and organization-isolation checks. Post-migration advisors found no warning- or error-level issues. Production remains on CSV.

Objective

Implement the Supabase Postgres storage adapter while keeping:

RATE_STORAGE_BACKEND=csv

as the default.

Connection approach

FastAPI needs server-side transactional database access.

Use a maintained Postgres driver/pool suitable for the existing synchronous FastAPI architecture.

For example, a current psycopg/pool approach is reasonable.

Do not put the DB connection string in frontend code.

Use:

SUPABASE_DB_URL

from Railway/server environment.

Require SSL.

Why direct Postgres from FastAPI

Approval/replacement needs a real transaction.

For example:

old carrier import: approved -> archived
new import: pending_review -> approved

must not leave the system halfway updated.

Do not implement this as unrelated REST calls that can partially succeed.

Organization isolation

Every repository operation must require an explicit:

organization_id

Do not permit application code to execute unscoped business queries such as:

select * from rate_offers;

Application queries should always be organization-scoped.

RLS remains defense in depth for direct Supabase/Data API access.

FastAPI remains responsible for authenticated request authorization.

Pydantic -> Postgres mapping

Create explicit mapping functions.

Do not sprinkle ad-hoc dictionary translations across service methods.

Examples:

source_document_to_db(...)
rate_import_to_db(...)
rate_card_to_db(...)
rate_offer_to_db(...)
rate_charge_line_to_db(...)
rate_note_to_db(...)

and corresponding row-to-model functions where needed.

Metadata

Use typed columns for common searchable fields.

Use metadata jsonb only for:

parser-specific attributes;

fields not worth promoting yet;

forward-compatible extra information.

Do not move the entire Pydantic object into JSONB and ignore the relational columns.

Tests

Implement repository-level integration tests.

They must verify at least:

source document insertion;

checksum dedupe within one organization;

same checksum allowed across different organizations;

import insertion;

card insertion;

bulk offer insertion;

bulk charge insertion;

notes insertion;

reading an import back;

organization isolation.

application string IDs round-trip unchanged while UUID PKs remain internal.

Integration tests should use disposable test data and clean it afterward.

Do not let automated tests delete real client organizations/data.

Performance requirement

Do not insert thousands of offers/charges one row at a time if a batched method is available.

The known carrier parsers can create hundreds/thousands of rows per import.

Use bulk insert methods.

Acceptance gate

A known real source document should be persisted to Postgres and read back with:

same card count;

same offer count;

same charge count;

same note count;

same important field values.

But production runtime remains on CSV.

Stop here

Do not change the Rate Desk read path yet.

STAGE 5 — Move import persistence + approval lifecycle to Postgres

Implementation status: complete on 9 August 2026. Production remains on the CSV backend until Stage 6.

Objective

Make Postgres capable of owning the complete import/review/approval lifecycle.

This is where the new database model starts delivering architectural value.

New import behavior

Current conceptual flow:

upload
  ->
parse
  ->
run artifacts
  ->
pending review
  ->
approval copies into published CSV warehouse

Target Postgres flow:

upload
  ->
parse
  ->
run artifacts
  ->
persist source/import/card/offers/charges/notes immediately
  ->
rate_import.status = pending_review
  ->
approval changes status to approved

The parsed data exists before approval.

It is simply not considered live.

Preserve filesystem run artifacts for now

Do not move:

data/runs/<import_id>/

to Supabase Storage in this stage.

Continue creating:

snapshot;

detected structure;

parsed CSVs;

canonical JSON;

validation report;

review Markdown;

tier tables where applicable;

approval artifact if current UI/tests rely on it.

This keeps parser/review debugging unchanged while database cutover happens.

Approval semantics

In one DB transaction:

lock/select the target import;

verify it is approvable;

verify there are no blocking validation errors;

if it has a carrier_key, archive the currently approved import(s) for:

same organization_id;

same carrier_key;

mark new import approved;

set approved_at;

set approved_by;

commit.

If anything fails:

rollback entire transaction

Do not delete the archived rates.

History is a feature.

Rejection

Rejection should update:

status = rejected
rejected_at
rejected_by
rejection_reason

Parsed data remains for historical/review purposes.

Deletion

Delete behavior should cascade through:

rate_import
 -> rate_card
 -> rate_offers
 -> charge_lines
 -> notes

Source-file deletion policy should remain explicit.

Do not accidentally remove a raw source merely because an import is deleted unless the product intentionally chooses that behavior.

Live-data rule

Introduce one centralized rule:

Rate Desk/search returns only data whose parent rate_import.status = 'approved'.

Do not copy rows into a second "published" table.

Comparison testing

For each known parser family:

import using existing CSV flow;

import same source into Postgres;

compare:

status;

template;

card fields;

offer count;

charge count;

note count;

representative values;

approval outcome.

At minimum cover the real samples already used by the test suite.

Specially verify:

standalone UK haulage;

MSC zoned joins;

Hapag conditional charges;

COSCO PDF pricing components.

Stop here

It is acceptable at this checkpoint for UI reads to remain on the CSV implementation while DB persistence is validated.

Do not cut over /api/rate-desk yet.

STAGE 6 — Move Import UI and Rate Desk reads to Postgres

Objective

Switch the read path from CSV warehouse files to Supabase Postgres while preserving the API response shapes expected by the existing frontend.

APIs to migrate

GET /api/imports
GET /api/imports/{id}
GET /api/search
GET /api/rate-desk

Import list

Read from:

source_documents
JOIN rate_imports

scoped by:

organization_id

Preserve the fields consumed by the current Import UI.

Import review detail

Read structured entities from Postgres:

rate_import
rate_card
rate_offers
rate_charge_lines
rate_notes

Run artifacts may still be read from filesystem where needed.

Do not remove review artifact support just because structured data is now in DB.

Search

Search should:

require organization_id;

include only approved imports;

filter using DB columns where practical:

provider;

carrier;

collection;

POL;

POD;

equipment;

validity/date;

return the same response contract expected by the UI.

Rate Desk

Initially preserve current Rate Desk shaping/calculation in Python.

The first DB cutover should be:

Postgres supplies the entities
services.py keeps applying existing business semantics

Do not simultaneously rewrite all commercial calculations into SQL.

That would make regression debugging unnecessarily difficult.

Important pricing rule

The database stores what the carrier/source said.

Existing application logic decides what contributes to the displayed/computed rate.

For the current COSCO PDF parser:

COSCO
  Freight Rate          parsed + persisted + priced
  EFS                   parsed + persisted + priced
  collection IHL        parsed + persisted + priced
  Documentation         currently excluded
  Destination handling currently excluded
  other tariff lines   currently excluded

Do not expand extraction coverage during the persistence migration.

The rule for this project is parity with the current parser, not a richer future-state representation.

Do not change these semantics during the persistence migration.

The future rules/settings engine is out of scope.

Merchant haulage

Preserve the current rule that only standalone haulage sources feed the merchant-haulage tariff lookup.

Carrier SD / CY products must not leak into the standalone haulage lookup.

Regression comparison

For a known populated dataset run the same searches against:

CSV repository
Postgres repository

Compare normalized responses.

Fields which are allowed to differ should be limited to things such as generated database UUIDs/timestamps, not commercial results.

Acceptance gate

The client-facing UI should look and behave materially the same before and after changing:

RATE_STORAGE_BACKEND=csv

to:

RATE_STORAGE_BACKEND=postgres

Stop here

Do not remove CSV support immediately.

Keep it as a rollback mechanism through the trial.

STAGE 7 — Production cutover for trial

Objective

Make authenticated Supabase/Postgres mode the deployed default.

Deployment configuration

Railway should have server secrets/config for:

SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
SUPABASE_DB_URL

AUTH_REQUIRED=true
RATE_STORAGE_BACKEND=postgres

Do not expose:

SUPABASE_DB_URL

through /api/public-config.

Trial users

Before deployment:

invite the client users through Supabase Auth;

create the Reudan organization if it has not been created;

add each invited auth.users.id to organization_members;

assign roles deliberately.

Suggested trial roles:

client power users -> operator
client search-only users -> viewer
internal owner/admin -> admin

Invitation acceptance and password setup

This is required before inviting the full client trial group.

The current Stage 2 login screen supports email/password sign-in, but it does not let a newly invited user choose a password. Do not assume that Supabase supplies this application screen automatically.

Add a dedicated invitation-acceptance page, for example:

UI/set-password.html
UI/set-password.js

The page must:

accept the Supabase invitation session from the email link;

show new-password and confirm-password fields;

validate that the two values match and meet the configured password rules;

set the password with the authenticated Supabase client;

verify organization membership through GET /api/me;

redirect an authorized user to the Rate Desk;

show a clear expired/invalid-link message without exposing internal details;

deny application access when no organization_members row exists.

Configure the Supabase invite redirect to this page and add the exact URL to the allowed redirect URLs. Keep public signup disabled. Never put a Supabase secret or service-role key in this page.

Add automated and manual checks for:

new invited user can choose a password and sign in again later;

password confirmation mismatch is rejected;

expired or reused invitation link is handled safely;

invited user without an organization membership cannot access rate data;

existing email/password login and logout still work.

Smoke test

Logged out:

UI -> login
/api/rate-desk -> 401
/api/imports -> 401

Viewer:

Rate Desk -> works
Import list -> works
Upload -> forbidden
Approve -> forbidden

Operator:

upload -> works
review -> works
approve -> works
search -> works

Replacement:

old carrier source approved
new carrier source uploaded
old remains live during review
new approved
old becomes archived
new becomes live

Rollback

Rollback must be simple:

RATE_STORAGE_BACKEND=csv

if a Postgres-read regression is discovered.

Do not delete CSV support until after the client trial is stable.

Note:

Any imports created only in Postgres after cutover will not magically exist in the old CSV store.

Therefore rollback is a short-term emergency mechanism, not a permanent dual system.

If true bidirectional rollback is required, implement an explicit temporary dual-write period and reconciliation checks; otherwise avoid dual-write complexity.

Stop here

This is a suitable end state for next week's full client trial.

Everything below is optional/post-trial hardening.

STAGE 8 — Move raw uploaded sources to Supabase Storage

Implementation status: complete on 10 August 2026. The private bucket and organization-scoped RLS policies are applied. The application keeps a temporary parser file, uploads the accepted immutable original with the signed-in user's token, and stores the object path in PostgreSQL. Live role and cross-organization acceptance tests pass.

Objective

Remove reliance on the Railway persistent volume for original uploaded carrier documents.

This is intentionally after Auth + DB cutover.

Current target

Use a private Supabase Storage bucket, for example:

rate-sources

Potential object structure:

<organization_id>/<source_document_id>/<original_filename>

Requirements

bucket is private;

no anonymous access;

user access is organization-scoped;

server may upload the source after FastAPI accepts it;

source_documents.storage_path stores the object path;

checksum remains stored in Postgres;

parser still receives a local temporary file path where required.

Do not combine with parser refactor

The inspector/parsers currently expect filesystem sources.

A safe flow is:

upload
 -> FastAPI temp/local path
 -> parser
 -> upload immutable original to Supabase Storage
 -> persist storage path

Later, historical re-processing can download the object into a temp path.

Acceptance tests

upload survives Railway redeploy;

authorized user can retrieve/download through the application if that feature exists;

unauthorized org cannot access object;

deleting/rejecting an import does not accidentally delete the source unless explicitly requested.

STAGE 9 — Post-trial performance/hardening

Do not pull this work into the auth/DB migration unless needed for trial stability.

9.1 Pagination / slim Rate Desk response

The current application can request thousands of Rate Desk rows including:

raw charges;

notes;

expanded charge analysis.

This creates large responses and expensive DOM work.

Postgres now makes it practical to implement:

/api/rate-desk
  -> paginated/slim rows

/api/rate-desk/{offer_id}
  -> lazy detail

Also consider:

separate filter metadata endpoint;

query cancellation;

server-side sorting;

pagination/cursors.

Do this only after parity with the current UI is proven.

9.2 Pricing/settings rules

Future tables may include:

pricing_rule_sets
pricing_rules

Example use:

COSCO:
  Freight Rate          display=true  price=true
  EFS                   display=true  price=true
  IHL                   display=true  price=true
  Documentation         display=true  price=false
  Destination Handling  display=true  price=false

Do not build this during the persistence migration.

First prove the DB using the existing hard-coded carrier semantics.

9.3 Saved customer quotations

Out of scope.

The client's immediate requirement is a private rate library used to quote customers.

Do not create:

quotes
quote_lines
customers
CRM tables
margin tables

until the product actually needs saved quotation history.

6. Detailed access model

Viewer

Allowed:

GET /api/me
GET /api/imports
GET /api/imports/{id}
GET /api/search
GET /api/rate-desk

Forbidden:

POST /api/imports
POST /api/imports/{id}/approve
POST /api/imports/{id}/reject
DELETE /api/imports/{id}

Operator

Allowed:

all viewer operations
upload/import
approve
reject
delete/archive according to existing product behavior

Admin

For the initial trial:

same rate-data rights as operator

Later admin can gain:

invite/remove member;

role management;

organization settings;

pricing rules.

Do not add those account-management screens now.

7. Request context rule

Every authenticated business request should end up with a context similar to:

RequestUser(
    user_id=...,
    email=...,
    organization_id=...,
    role=...,
)

Service/repository code should receive organization_id explicitly.

Avoid hidden global organization state.

Avoid hard-coding the Reudan organization UUID inside Python code.

8. Database transaction rules

Use database transactions for operations which must be atomic.

At minimum:

Import bundle creation

Prefer one transaction for:

source/import
card
offers
charge lines
notes

If bulk insertion fails part-way through:

rollback

Do not leave a half-created rate card.

Approval/replacement

One transaction:

archive superseded carrier import
approve new import
write approval metadata

Delete

One transaction/cascade path.

9. ID strategy

The current application already has stable string IDs, for example:

offer_ab12...

The remote Supabase schema currently has UUID primary keys.

Do not choose between them by replacing one with the other.

Use both:

id              uuid primary key
application_id  text not null

id is an internal relational database key.

application_id preserves the current parser/application identifier used by:

Pydantic models;

API payloads;

run artifacts;

source references;

existing tests;

cross-entity application logic.

Before Postgres cutover, add application_id to the persisted entity tables and create suitable organization-scoped uniqueness constraints/indexes.

The repository layer must map explicitly:

application string ID
        <->
database UUID PK

Where the existing code refers to another entity by its application ID, do not force the whole codebase to adopt database UUIDs during this migration.

Database foreign keys should continue using UUID PKs internally.

Application/API behavior should continue using the current string IDs unless a separate deliberate API migration is planned.

This dual-ID approach is the required migration strategy.

10. Source checksum semantics

Current source registration deduplicates based on SHA-256.

The Postgres schema enforces:

UNIQUE (organization_id, sha256)

Therefore:

same file uploaded twice to same org
 -> deduplicated / existing source behavior

same file uploaded by two different orgs
 -> allowed as separate source records

Preserve current user-facing duplicate behavior as closely as practical.

11. Date/currency/amount handling

Amounts

Database amount fields use numeric types.

Never convert commercial amounts to floating-point before persistence.

Use Python Decimal end-to-end where the current models permit it.

Dates

Use actual Postgres date columns for:

valid_from
valid_to

Do not store normal validity dates only in JSON/text.

Currency

Keep the existing currency semantics.

Do not add a currencies reference table during this migration.

Static FX remains unchanged until a separate pricing/FX project.

12. Keep run artifacts during the migration

Postgres is replacing the searchable/published warehouse.

It does not need to immediately replace the parser's diagnostic artifacts.

Continue producing:

source_snapshot.json
detected_structure.json
rate_import.json
parsed_rate_cards.csv
parsed_rate_offers.csv
parsed_rate_charge_lines.csv
parsed_rate_notes.csv
canonical_rates.json
validation_report.json
review.md
tier_rate_tables.json
approval.json

where currently applicable.

These are useful debugging/evidence artifacts and make parser regressions easier to diagnose during the DB transition.

Storage migration can happen later.

13. Things the agent must NOT do

Do not:

rewrite parser families;

introduce an LLM parser;

redesign the Rate Desk UI;

introduce React/Next.js;

add saved quotations;

add CRM/customer tables;

add a generalized pricing rules engine;

normalize carriers/ports/equipment into dozens of new reference tables;

expose the Postgres connection string in the browser;

expose a Supabase secret/service key in the browser;

use user_metadata for authorization;

leave CORS as *;

rely only on frontend route hiding for security;

delete archived historical rates on replacement;

switch storage backend before parity tests pass;

remove CSV fallback before the trial is stable;

change current carrier price composition during DB migration;

convert Decimal financial values to float unnecessarily.

replace existing application string IDs with UUIDs in API/parser behavior as part of this migration.

expand the COSCO parser to capture documentation/destination handling during this migration.

14. Test matrix before client trial

The final pre-trial test should cover the full product flow.

Authentication

logged out -> login shown
logged out API call -> 401
bad JWT -> 401
no org membership -> 403
viewer -> reads only
operator -> reads + mutations
logout -> access removed

Import

For every supported real-sample family practical:

upload
inspect
template match
parse
validation
review
pending_review
approve

Verify counts and representative values.

Approval

pending import invisible to live Rate Desk
approved import visible
rejected import invisible
archived import invisible

Replacement

old approved carrier contract remains live
new contract uploaded and reviewed
new contract approved
old contract archived
new contract becomes live

Search/Rate Desk

Verify:

collection
POL
POD/destination
equipment
material
routing mode
validity/expiry
sorting
quantity calculation
charge expansion

Carrier-specific regression checks

Verify:

standalone haulage remains separate
MSC zoned Special/Tariff semantics remain correct
Hapag conditional surcharges remain correct
COSCO PDF Freight + EFS + IHL pricing remains correct
CMA constrained EML behavior remains correct
Maersk parser behavior remains correct

Security

Verify:

no unauthenticated rate API access
no cross-organization access
no browser secret keys
no wildcard CORS
RLS enabled
Supabase security advisor clean

15. Recommended agent-session boundaries

If agent/model usage is constrained, use these exact sessions.

Agent session A

Only:

Stage 0
Stage 1

Deliver:

schema captured;

auth primitives;

/api/me;

tests.

Then stop.

Agent session B

Only:

Stage 2

Deliver:

login;

JWT API wrapper;

API protection;

membership/role enforcement;

CORS;

tests.

Then stop and manually test the authenticated existing CSV application.

Agent session C

Only:

Stage 3

Deliver:

persistence abstraction;

CSV implementation behind it;

zero behavior change;

all existing tests green.

Then stop.

Agent session D

Only:

Stage 4

Deliver:

Postgres repository;

mappings;

transactions/bulk writes;

repository integration tests.

Do not change production backend selection.

Agent session E

Only:

Stage 5

Deliver:

Postgres import bundle;

approval/rejection/archive/delete lifecycle;

parity tests against existing behavior.

Then stop.

Agent session F

Only:

Stage 6

Implementation status: complete on 9 August 2026. Import review, search, and Rate Desk reads now use the selected repository backend.

Deliver:

Postgres reads;

search;

Rate Desk;

comparison tests.

Then stop.

Agent session G

Only:

Stage 7

Implementation status: code complete on 10 August 2026. Production configuration, deployment, and authenticated smoke-test evidence remain to be verified before the trial is complete.

Deliver:

production configuration;

cutover;

smoke tests;

trial-ready deployment.

Do not automatically continue into Stages 8/9.

16. Definition of done for next week's trial

The project is trial-ready when:

[ ] Client cannot see rates without signing in.
[ ] Public signup is disabled.
[ ] Client users are explicitly invited.
[ ] Every client user belongs to the correct organization.
[ ] API endpoints enforce authentication.
[ ] Mutation endpoints enforce operator/admin roles.
[ ] CORS is restricted.
[ ] New imports persist to Supabase Postgres.
[ ] Pending imports can be reviewed normally.
[ ] Approval makes an import live without copying rows.
[ ] Replacement archives the prior same-carrier import transactionally.
[ ] Rate Desk reads approved Postgres rates.
[ ] Existing parser semantics are unchanged.
[ ] Existing Rate Desk calculations are unchanged.
[ ] Real carrier sample regression tests pass.
[ ] Supabase security advisor is clean.
[ ] Railway contains no browser-exposed secrets.
[ ] A tested rollback path exists.

17. Immediate next action

Start with Stage 0 only.

Before writing application code:

inspect the current repository;

capture the already-created remote Supabase schema into source control;

run the existing test suite;

commit;

stop.

Then start Stage 1 in a fresh agent context/session.

The migration should optimize for:

boring, reversible, testable steps over a clever one-shot rewrite.
