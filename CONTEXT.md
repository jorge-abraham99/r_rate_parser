# Repository Architecture Context

Last verified: 8 August 2026

This is the current architecture handoff for the Reudan freight-rate parser and Rate Desk. It describes the repository as implemented now. `mvp.md`, `freight_rate_scripting_phase_plan.md`, and `current_progress_and_next_steps.md` contain useful product history, but parts of them predate the connected UI, approval workflow, and newer parser families.

## Product and Trust Boundary

The application converts known carrier rate documents into reviewable, searchable freight offers. Parsing is deterministic and template-driven. Unknown formats fail explicitly instead of being interpreted speculatively.

Human approval is the publication boundary:

- importing creates a private run and review pack;
- validation errors block approval, while warnings do not;
- only approved entities enter the searchable warehouse;
- approving a replacement with the same `carrier_key` archives the previous import and removes its published rows.

There is no LLM or external AI service in the runtime path.

## System Shape

```text
Import UI or CLI
       |
       v
FastAPI / service layer
       |
       +--> RateRepository business persistence boundary
       +--> structural inspection
       +--> YAML template scoring
       +--> carrier-specific deterministic parser
       +--> validation and review artifacts
       |
       v
Human approval
       |
       v
CsvRateRepository
       |
       +--> source registry and checksum deduplication
       +--> CSV/JSON warehouse
       |
       +--> search API
       +--> Rate Desk aggregation and charge analysis
       |
       v
Quote UI
```

The application is currently a single Python web process with local filesystem persistence. Supabase Auth and membership lookup are active, but rate persistence is not connected to Postgres yet. There is no queue, worker, or frontend build service.

## Repository Map

### Backend

- `rate_ingest/api.py`: FastAPI routes, upload handling, health/public configuration, authorization dependencies, and static UI mount.
- `rate_ingest/auth.py`: mockable Supabase bearer-token validation, RLS-backed membership lookup, request context, and role gates.
- `rate_ingest/services.py`: central orchestration for imports, review detail, approval/rejection, archive/delete, search, Rate Desk shaping, charge grouping, and static FX conversion.
- `rate_ingest/repositories/base.py`: business persistence interface and approved-rate library result.
- `rate_ingest/repositories/csv_repository.py`: active adapter over the existing source registry and CSV warehouse.
- `rate_ingest/repositories/postgres_repository.py`: Stage 4 organization-scoped Postgres adapter with pooled connections, transactions, and batched child writes.
- `rate_ingest/repositories/postgres_mappings.py`: explicit Pydantic-to-relational mappings and reverse mappings.
- `rate_ingest/repositories/__init__.py`: selects the repository from `RATE_STORAGE_BACKEND`.
- `rate_ingest/models.py`: Pydantic models for source documents, imports, cards, offers, charge lines, notes, validation, templates, and canonical rates.
- `rate_ingest/config.py`: resolves the data root and creates/seeds required directories.
- `rate_ingest/source_registry.py`: copies uploaded sources into raw storage and deduplicates registrations by SHA-256 checksum.
- `rate_ingest/inspector.py`: extracts structural signals from Excel, CSV, EML, and text-based PDF inputs.
- `rate_ingest/template_matcher.py`: loads templates, enforces file-type compatibility, scores matches, and selects the best template at confidence `>= 0.55`.
- `rate_ingest/parsers/`: carrier/document-specific deterministic parsers.
- `rate_ingest/normalize.py`: shared text, equipment, amount, and date normalization.
- `rate_ingest/validate.py`: blocking and non-blocking validation rules.
- `rate_ingest/review.py`: Markdown review-pack generation.
- `rate_ingest/approve.py`: approval/rejection decisions. It publishes and updates records through `RateRepository`.
- `rate_ingest/warehouse.py`: CSV warehouse paths and low-level append/remove/rebuild operations used only by `CsvRateRepository`.
- `rate_ingest/canonical.py`: minimal canonical export generation from offer base amounts.
- `rate_ingest/email_source.py`: constrained EML body and HTML-table extraction.
- `rate_ingest/cli.py`, `rate_ingest/search.py`: Typer commands and terminal search output.
- `rate_ingest/utils.py`: checksum, safe-copy, JSON, and CSV helpers.

### Frontend

- `UI/import.html`, `UI/app.js`: connected upload, review, publish, archive, deletion, source cadence, and parse-summary interface.
- `UI/index.html`, `UI/rate-desk.js`: connected quote filtering, routing comparison, sorting, quantity calculation, and expandable charge details.
- `UI/styles.css`: shared visual system.
- `UI/config.js`: runtime mode switch. `demoMode` is currently `false`, so both screens call the backend.
- `UI/demo-data.js`: browser-only fixtures retained for demo mode.
- `UI/Rate Lookup v1.dc.html`, `UI/support.js`, and `UI/rates/`: legacy/prototype assets, not the active connected Rate Desk path.

### Configuration and deployment

- `data/templates/`: operator-editable parser templates.
- `rate_ingest/bundled_templates/`: package-owned defaults deployed with the application.
- `requirements.txt`: Railway installation manifest.
- `pyproject.toml`: Python package metadata, dependencies, package-data rules, and pytest configuration.
- `railway.json`: Uvicorn start command, `/api/health` health check, and restart policy.
- `DEPLOY_RAILWAY.md`: deployment and persistent-volume instructions.
- `supabase/config.toml`: Supabase CLI configuration targeting PostgreSQL 17.
- `supabase/migrations/`: exact local copies of the two migrations already applied to the hosted `carrier-quotes` project.
- `supabase/README.md`: Stage 0 database baseline, security posture, credentials, and deferred ID reconciliation.
- `.env.example`: non-secret Supabase environment variable template; `.env` is ignored.
- `tests/test_rate_ingest_cli.py`: end-to-end CLI/API coverage with real source documents.
- `tests/test_repositories.py`: storage selection, CSV adapter parity, and service-boundary checks.

Keep `requirements.txt` and `pyproject.toml` synchronized. Railway currently installs from `requirements.txt`.

## Import Lifecycle

`services.import_source_file()` owns the normal ingestion transaction:

1. `Settings.ensure()` creates data directories and seeds missing bundled templates.
2. `RateRepository.register_source_document()` copies and registers the source. The active CSV adapter writes `source_documents.csv`.
3. `classify_source()` calls the inspector and template matcher.
4. The selected parser returns one `RateCard` and collections of `RateOffer`, `RateChargeLine`, and `RateNote`.
5. Validation sets the import to `pending_review` or `failed` when blocking errors exist.
6. Detailed CSVs, canonical JSON, inspection output, validation, and review Markdown are written to a run directory.
7. The repository adds the import record. The active CSV adapter writes the warehouse import ledger.
8. Approval publishes detailed rows and canonical rates through the repository. Rejection keeps the run but does not publish it.

Known import statuses are `pending_review`, `failed`, `approved`, `rejected`, and `archived`.

FastAPI turns parser/template `ValueError`s into HTTP 422 responses. Other unexpected exceptions currently surface as server errors. Upload parsing is synchronous in the request process.

## Inspection and Template Selection

Inspection produces an `InspectResult` containing source type, provider guess, parser-family guess, page/sheet summaries, and scored candidate templates.

- Excel uses OpenPyXL sheet names, dimensions, and top-row previews.
- CSV inspection reads a small top-row preview, although no active CSV-specific template is currently configured.
- EML inspection reads the latest supported body and HTML tables.
- PDF inspection uses PyMuPDF and therefore supports text-based PDFs only; it does not run OCR.

Template loading has two layers:

1. bundled templates are loaded from `rate_ingest/bundled_templates/`;
2. templates with the same ID in `data/templates/` override the bundled version.

`Settings.ensure()` also copies a bundled template into `data/templates/` when it is absent, without overwriting operator-managed files. Loading bundled templates directly prevents a stale persistent Railway volume from hiding a newly deployed parser.

Scoring uses compatible file type, filename tokens, sheet-name signals, required headers, provider guess, and parser-family guess. The COSCO Tuticorin PDF has a deliberate strong filename rule as a fallback when PDF text ordering varies between PyMuPDF builds.

## Parser Coverage

| Family | Template | Input and behavior |
| --- | --- | --- |
| `tabular_lane` | `msc_far_east_v1` | Structured MSC lane workbook |
| `matrix` | `cosco_matrix_v1` | COSCO origin/destination Excel matrix |
| `cosco_pdf_quote` | `cosco_pdf_quote_v1` | Text-based COSCO India/Far East door-to-quay PDF |
| `offer_block` | `maersk_offer_block_v1` | Repeated Maersk offer and surcharge blocks |
| `site_to_site_rows` | `maersk_afls_site_to_site_v1` | Maersk AFLS site-to-site quote rows and charge codes |
| `haulage_matrix` | `uk_haulage_matrix_v1` | Standalone UK collection-to-port inland tariff |
| `msc_zoned_inline` | `msc_zoned_inline_v1` | MSC city/POL zone joined to Special and Tariff door-to-quay rates |
| `hapag_door_matrix` | `hapag_door_matrix_v1` | Hapag-Lloyd collection/POD door-to-quay matrix |
| `email_table` | `cma_email_table_v1` | Constrained CMA HTML table in an EML body |

### Carrier-specific rules worth preserving

- **Standalone UK haulage:** `document_type=inland_export`; these rows alone feed the merchant-haulage tariff lookup.
- **MSC zoned:** joins each city/POL zone to both `REUDAN-SPECIAL` and `REUDAN-TARRIFF`. It publishes `SD / CY` carrier offers, never standalone haulage. The two original 252-row tier tables are also saved in `tier_rate_tables.json`. `Bristol` is aliased to `PORTBURY` for the join.
- **Hapag-Lloyd:** expands collection locations in column C across POD columns D-J, preserving preferred POL and routing. Every offer adds USD 15 live position; Binh Duong Terminal and Lat Krabang also add USD 20 emergency fuel. Equipment defaults to `40HC` because the workbook has no equipment field.
- **COSCO PDF:** uses PDF word coordinates rather than text ordering for the 40GP/40HC table columns. It creates 38 collections x 2 equipment sizes for the Tuticorin sample. Only Freight Rate, EFS, and collection IHL affect price; documentation, destination handling, and other tariff lines are excluded. It publishes `SD / CY` carrier offers.
- **CMA EML:** intentionally supports a narrow latest-body HTML-table structure, not arbitrary quoted history or attachments.

Adding a parser family requires a parser module, `parse_source_by_family()` dispatch, a template in both template directories, inspector recognition when needed, model support for any parser-specific rules, and a real-sample end-to-end test.

## Data Model

- `SourceDocument`: registered source metadata, path, uploader, checksum, and source type.
- `RateImport`: parser/template selection, confidence, lifecycle status, validation summary, and approval metadata.
- `RateCard`: document-level provider, carrier, commodity, currency, validity, and all-in semantics.
- `RateOffer`: searchable collection/origin/POL/POD/destination/equipment/service combination and base amount.
- `RateChargeLine`: component charge, amount, currency, basis, explicit type, and inclusion flag.
- `RateNote`: card- or offer-level commercial/routing text with source reference.
- `ValidationReport` and `ValidationItem`: severity-count summary and evidence-linked findings.
- `CanonicalRate`: minimal export containing type, raw from/to, base amount, currency, unit, and validity.

The canonical export intentionally contains the offer base amount only. It is not the Rate Desk's computed total and does not contain the full charge breakdown.

## Repository and Filesystem Storage

`RateRepository` is the only business persistence boundary used by services, approval, CLI search, and CLI inspection. `CsvRateRepository` is the active adapter. `PostgresRateRepository` is available for Stage 4 integration tests. The existing `source_registry.py` and `warehouse.py` modules remain as low-level CSV implementation details.

`RATE_STORAGE_BACKEND` defaults to `csv`. Selecting `postgres` requires `SUPABASE_DB_URL` and an explicit organization UUID for every repository operation. The adapter requires SSL, disables prepared statements for transaction-pooler compatibility, reuses a small connection pool, and uses batched child inserts. The application-ID migration and real-database integration test passed, but the deployed backend remains `csv` until the later lifecycle and read-cutover stages.

The data root defaults to the current working directory and can be replaced with `RATE_INGEST_ROOT`. All mutable application state is under `<root>/data/`.

```text
data/
  sources/
    raw/                         copied uploads
    registered/source_documents.csv
  templates/                    operator template overrides
  runs/<import_id>/
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
    tier_rate_tables.json        MSC zoned imports only
    approval.json                after approval/rejection
  warehouse/
    rate_imports.csv
    approved_rate_cards.csv
    approved_rate_offers.csv
    approved_rate_charge_lines.csv
    approved_rate_notes.csv
    approved_rates.csv           rebuilt minimal canonical export
```

Deleting an import removes its run and its published/import-ledger rows. It does **not** currently remove the registered source record or copied raw source file.

There is no transaction, file lock, or multi-process coordination around these CSV rewrites.

## Supabase Migration Baseline

Stage 0 of `SUPABASE_AUTH_AND_RATE_DB_MIGRATION_PLAN.md` has captured, but not activated, the hosted database target:

- project `carrier-quotes`, reference `vwwnnvdusutyucsnndyc`, region `eu-west-1`;
- PostgreSQL 17.6;
- eight public tables matching the current persisted entities;
- RLS enabled on every public table;
- no `anon` table privileges;
- membership-scoped authenticated policies and service-role grants;
- zero Security Advisor findings at capture time.

The remote migration ledger contains `20260807222346_initial_rate_library_schema`, `20260807222404_add_missing_fk_indexes`, and `20260808150650_add_application_ids`. They must not be replayed against the existing project.

Supabase rate persistence is not yet the deployed runtime path: imports, approvals, and searches still use the existing filesystem behavior. Stage 4 migration `20260808150650_add_application_ids.sql` is applied remotely. It adds organization-scoped `application_id` values to `source_documents`, `rate_imports`, `rate_cards`, `rate_offers`, `rate_charge_lines`, and `rate_notes`. UUIDs remain internal database keys while current string IDs remain authoritative in API payloads and artifacts.

Stage 1 added Supabase access-token validation through the public JWKS. Stage 2 added invite-only browser login and membership-aware API authorization. The server sends the verified user token to the Supabase Data API to read only that user's `organization_members` rows through RLS. It does not use `user_metadata`, a JWT secret, a database password, or a service-role key for authorization.

Stage 3 added the repository boundary with the CSV adapter still active. It did not change the hosted schema, Data API exposure, RLS, or production rate storage.

Stage 4 adds the Postgres adapter and explicit mappings without a production cutover. API routes now pass the authenticated organization ID into repository-backed service calls. The Postgres bundle writer validates relationships and writes cards, offers, charges, and notes in one short transaction. The guarded integration test passed with the real Hapag source and two temporary organizations; cleanup left zero test organizations and zero test rate rows.

`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_DB_URL`, `AUTH_REQUIRED`, and `RATE_STORAGE_BACKEND` are available through `Settings`. `AUTH_REQUIRED` defaults to `true`, and `RATE_STORAGE_BACKEND` defaults to `csv`. The public configuration endpoint returns only the URL, publishable key, and auth flag. The database URL remains server-only.

## API Surface

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Redirect to `/ui/login.html` |
| `GET` | `/api/health` | Railway/process health check |
| `GET` | `/api/public-config` | Return browser-safe Supabase URL, publishable key, and auth flag |
| `GET` | `/api/me` | Return the verified user and RLS-backed organization memberships |
| `GET` | `/api/imports?limit=` | Import/source list for the Import UI |
| `POST` | `/api/imports` | Multipart upload and synchronous parse |
| `GET` | `/api/imports/{id}` | Review detail, previews, validation, charge summary, and tier tables |
| `POST` | `/api/imports/{id}/approve` | Publish an import and optionally assign carrier metadata/key |
| `POST` | `/api/imports/{id}/reject` | Record rejection reason |
| `DELETE` | `/api/imports/{id}` | Remove the import run and related warehouse rows |
| `GET` | `/api/search` | Filter approved offers by provider, carrier, collection, POL, POD, equipment, and date |
| `GET` | `/api/rate-desk?limit=` | Quote rows, filters, and standalone haulage lookup; limit is capped at 5,000 |

`/api/me`, imports, search, and Rate Desk require a valid token and organization membership. Viewer, operator, and admin roles can read. Only operator and admin roles can upload, approve, reject, or delete. `/api/health`, `/api/public-config`, and static assets remain public. The UI and API use one origin, so the permissive CORS middleware was removed.

## Rate Desk Semantics

`search_approved_offers()` joins approved cards, offers, charge lines, notes, and source metadata in memory.

- Explicit charge types win; otherwise names are heuristically grouped into origin, freight, destination, or unmatched.
- A synthetic freight base line is added to the analysis when the offer has a base amount but no explicit base charge.
- `all_in_amount` is the base plus non-base charges in the same currency, unless the offer is marked all-in.
- `all_in_usd` converts all charge-analysis lines using static demo FX rates from `services.py`.
- Unknown currencies currently use a multiplier of `1.0`, so cross-currency ranking is indicative rather than financially authoritative.
- Material filters are inferred from commodity/source text for Paper, Metal, and Tyres.

Standalone haulage is identified only by `document_type=inland_export`, `carrier_key=haulage-q2`, or `contract_tag=HAUL`. Its collection/POL rates become `haulage_tariffs` for merchant-haulage comparisons. MSC, Hapag-Lloyd, COSCO PDF, and other carrier `SD / CY` products stay in carrier quote results and must never enter that lookup.

## Connected UI Behavior

The Import screen loads up to 500 imports and currently also requests up to 5,000 Rate Desk rows to build source comparisons. It recognizes dedicated source keys for MSC door-to-quay, Hapag-Lloyd door-to-quay, COSCO India/Far East door-to-quay, Maersk contract/door products, and standalone UK haulage.

The Quote screen initially requests `/api/rate-desk?limit=5000`, then uses `/api/search` for filtered server searches. It supports collection, POL, destination, equipment, material, routing mode, quantity, expiry visibility, and sorting. Merchant-haulage options combine a standalone inland tariff with compatible port-to-port carrier rates in the browser.

The current large-payload problem is architectural: Rate Desk rows include raw charges, notes, and a second expanded charge-analysis representation. With thousands of offers this creates multi-megabyte responses and expensive DOM rendering. GitHub issue `#13` tracks pagination, slim list rows, lazy detail loading, separate filter metadata, cancellation, and eventually database-backed queries.

## CLI

Run commands through `python -m rate_ingest`:

```bash
python -m rate_ingest inspect <source>
python -m rate_ingest import <source> [--template <template_id>]
python -m rate_ingest review <import_id>
python -m rate_ingest approve <import_id> --approved-by <name>
python -m rate_ingest reject <import_id> --reason <text>
python -m rate_ingest search [filters]
```

The hidden `inspect` command creates diagnostic inspection artifacts. CLI search and `/api/search` now use the same repository-backed service search path.

## Testing

The suite contains 15 end-to-end parser tests that use real carrier samples, 32 auth/configuration/UI contract tests, and 14 repository tests. It covers parser behavior, JWT claims, membership lookup, protected routes, role gates, public endpoints, same-origin policy, the browser auth contract, CSV parity, Postgres mappings, batch behavior, and repository-boundary enforcement. The real Postgres test is skipped unless its explicit environment flag and database URL are present.

Run:

```bash
pip install -r requirements.txt
pytest -q
```

Tests set `RATE_INGEST_ROOT` to a temporary directory. Preserve that isolation so tests do not mutate the repository's real warehouse.

## Railway Deployment

Railway starts:

```bash
uvicorn rate_ingest.api:app --host 0.0.0.0 --port $PORT
```

The service health check is `/api/health`. Attach a persistent volume at `/app/data`; without it, imported sources, review runs, approvals, and warehouse rows can disappear on restart or redeploy.

PyMuPDF is listed in both dependency manifests and is imported lazily by PDF-specific paths so a missing PDF dependency cannot prevent the API from starting.

## Current Constraints and Risks

- Runtime rate storage is the repository-backed CSV/JSON adapter; the captured Supabase rate tables are not connected yet.
- The Stage 4 Postgres adapter is verified, but import lifecycle ownership and Rate Desk read cutover remain future stages.
- The filesystem runtime has no transaction boundaries, multi-process locks, or concurrent-writer protection. Database migrations now exist only as a captured baseline.
- Authentication and membership role checks are active, but CSV storage is still one shared runtime warehouse. Organization-scoped rate persistence starts with the Postgres repository in Stage 4.
- Parsing and large response construction happen synchronously in the API process.
- No generic unknown-document parser or AI-assisted template drafting.
- PDF support is limited to the known text-based COSCO layout; there is no OCR/scanned-PDF path.
- CSV can be inspected, but no active CSV template is selectable under current strict file-type matching.
- EML support excludes arbitrary threads, attachments, and plain-text-only layouts.
- Static FX and the unknown-currency fallback make USD ranking non-authoritative.
- Import deletion leaves raw-source and source-registry records behind.
- Rate Desk list payloads duplicate charge information and can become very large.
- Validation is structural/commercially basic; approval remains essential.

## Safe Extension Checklist

When adding or changing a parser:

1. Inspect the real source and state the business pricing rule explicitly.
2. Add or update the deterministic parser.
3. Add the template to both `data/templates/` and `rate_ingest/bundled_templates/`.
4. Update `ParserTemplate` for any new rule section.
5. Add inspector/provider/family signals only as narrowly as necessary.
6. Add service dispatch and UI source mapping when it is a new published source.
7. Preserve raw source references and non-priced terms without accidentally adding them to totals.
8. Add a real-sample end-to-end test covering counts, validity, equipment, price composition, approval, search, and haulage separation.
9. Run the full suite and `git diff --check`.
10. Update this file and `README.md` when architecture or operational behavior changes.
