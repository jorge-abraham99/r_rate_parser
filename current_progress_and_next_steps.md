# Current Progress And Next Steps

## Snapshot

Date: July 16, 2026

The repo is currently in a working scripting-phase state, not a finished product UI.

What works today:

- deterministic local ingestion pipeline in `rate_ingest/`
- import flow for known files
- review pack generation
- approve / reject flow
- local warehouse publishing
- approved-rate search
- canonical output generation in the minimal JSON shape

Supported parser families today:

- `tabular_lane` for known MSC-style Excel sheets
- `matrix` for known COSCO-style Excel sheets
- `offer_block` for known MAERSK quote workbooks
- `email_table` for one constrained CMA-style `.eml` format

What was verified:

- `pytest -q` passes
- real sample workbook imports were already working for MSC / COSCO / MAERSK
- real sample email import worked for `RE_ Far East Wastepaper for April - Reudan.eml`

Important product truth:

- this is not an AI-first parser yet
- this does not parse random unknown files yet
- current parsing is template-based and deterministic

## Current Architecture

Current flow:

1. source file is registered
2. source is inspected
3. best template is matched
4. parser family runs
5. rows are validated
6. review artifacts are written to `data/runs/<import_id>/`
7. approved rows are published to `data/warehouse/`

Current interfaces:

- CLI only for real operation
- static UI prototype in `UI/`

Important files:

- `rate_ingest/cli.py`
- `rate_ingest/inspector.py`
- `rate_ingest/template_matcher.py`
- `rate_ingest/parsers/`
- `rate_ingest/review.py`
- `rate_ingest/approve.py`
- `rate_ingest/warehouse.py`

## UI Status

The `UI/` folder is useful, but it is currently a design prototype, not an integrated app.

What is in `UI/`:

- `UI/Rate Lookup v1.dc.html`
- `UI/support.js`
- `UI/README.md`
- sample rate sheets under `UI/rates/`

What the prototype does:

- shows a lookup screen for RFQ -> best rate
- uses hard-coded sample data
- sorts and ranks rates client-side
- demonstrates the target operator experience

What it does not do yet:

- upload files
- call the parser
- read approved rates from the local warehouse
- show real review packs
- trigger approve / reject

Judgement:

- the UI file is good as a design reference
- it should not be treated as the parser integration itself
- the right move is to connect a thin web/API layer to the existing parser services, then feed real parsed data into a simplified version of this UI

## Recommended Direction

Do not replace the parser architecture.

Instead:

1. extract the current CLI actions into reusable service-layer functions
2. expose those functions through a minimal local web API
3. connect the UI to that API
4. only after that, add unknown-file handling and LLM assistance

Why this is the right sequence:

- it preserves the working deterministic import pipeline
- it avoids duplicating parsing logic between CLI and UI
- it lets the UI become a thin operator shell over real data
- it keeps unknown-file / LLM work isolated as the next phase instead of mixing it into the UI integration

## Proposed Next Phase

### Phase 1: Internal Service Layer

Goal: stop treating `cli.py` as the only entrypoint.

Refactor into reusable functions such as:

- `run_import(source_path, template=None, uploaded_by=None)`
- `get_import_review(import_id)`
- `approve_import_run(import_id, approved_by)`
- `reject_import_run(import_id, reason)`
- `search_approved_rates(filters)`
- `list_recent_imports()`

Outcome:

- CLI remains as a wrapper
- future API and UI can call the same logic

### Phase 2: Minimal Local API

Goal: add a thin local backend for the UI.

Recommended stack:

- FastAPI backend
- existing Python parser code unchanged underneath
- static frontend served separately or from FastAPI

Recommended endpoints:

- `POST /api/imports`
  - upload a file
  - run inspection + template match + import
  - return `import_id`, parser family, template used, counts, warnings

- `GET /api/imports`
  - list recent imports

- `GET /api/imports/{import_id}`
  - return summary, validation report, canonical rows, review metadata

- `POST /api/imports/{import_id}/approve`

- `POST /api/imports/{import_id}/reject`

- `GET /api/search`
  - search approved rates

- optional: `GET /api/templates`
  - show available deterministic templates

Outcome:

- UI can replace direct CLI usage for normal operators
- CLI remains available for debugging and batch work

### Phase 3: Connect The Existing UI Concept

Goal: make the prototype useful with real data.

Recommended approach:

- keep the visual design and operator flow from `UI/Rate Lookup v1.dc.html`
- do not depend on the hard-coded sample data model
- replace sample arrays with API calls

Suggested UI flow:

1. upload/import screen
2. import review screen
3. approved rate lookup screen

Why add those screens:

- the current prototype only covers approved-rate lookup
- the parser workflow also needs inspection, review, and approval
- if we skip those, the operator still has to fall back to CLI

If we want the fastest possible first UI:

- build only two screens first
- screen 1: upload + import result
- screen 2: approved rate lookup

### Phase 4: Unknown File Handling

Goal: handle files that do not match a current deterministic template.

This should not mean “let the LLM parse everything directly.”

Recommended unknown-file workflow:

1. upload file
2. inspector runs
3. if no template matches above threshold, mark as `unknown_format`
4. store source and structure snapshot
5. present a fallback review screen showing:
   - file name
   - detected sheets / tables
   - top rows preview
   - why no template matched
6. allow manual classification:
   - likely parser family
   - likely carrier
   - target sheet
7. pass that artifact into an LLM-assisted template drafting step

Outcome:

- unknown files become triageable, not silent failures

### Phase 5: LLM-Assisted Template Drafting

Goal: use an LLM to help create deterministic templates, not replace them.

Recommended LLM responsibilities:

- infer likely parser family
- suggest header mappings
- suggest row filters
- suggest sheet selection rules
- draft a candidate template YAML
- explain confidence and ambiguous fields

Recommended non-LLM responsibilities:

- final import logic
- canonical publication
- approval decisions
- validation rules

Required product rule:

- LLM output must remain a draft
- no LLM-generated parse should auto-publish without deterministic reviewable output

## Technical Recommendations

### 1. Keep Canonical Output Small

Keep the public export shape as:

- `rate_type`
- `from_raw`
- `to_raw`
- `amount`
- `currency`
- `unit`
- `valid_from`
- `valid_to`

Keep richer parser details internally for:

- review
- debugging
- UI breakdowns
- traceability

### 2. Add A UI-Facing Search View Model

The lookup UI needs more than the minimal canonical JSON.

The current UI design expects fields like:

- carrier
- source sheet
- all-in
- component breakdowns
- validity status
- fine print

So we should introduce a derived “search result view model” built from approved offers + charges + notes, instead of forcing the UI to reconstruct everything from the canonical export alone.

### 3. Add Import Statuses Explicitly

Useful statuses:

- `registered`
- `pending_review`
- `approved`
- `rejected`
- `failed`
- `unknown_format`

This will matter once the UI lists imports and queues.

### 4. Plan For Location Normalization Soon

The lookup UI will break down fast without location normalization.

Examples:

- Southampton
- SOU
- GBSOU
- Felixstowe
- FXT
- GBFXT

Recommended near-term addition:

- `location_aliases.csv` or equivalent mapping table
- normalization helpers for POL / POD / place of receipt / destination

Without this, search and UI filtering will look inconsistent.

## Suggested Execution Order

Recommended order for the next implementation phase:

1. extract service layer from CLI
2. add FastAPI endpoints
3. expose recent imports + import detail + search
4. build a minimal real UI against those endpoints
5. add unknown-file status and fallback review screen
6. add LLM-assisted template drafting for unknown files

## Concrete Deliverables For The Next Build

If we start implementation from this plan, the next practical deliverables should be:

- `rate_ingest/services.py` or similar
- local FastAPI app
- upload endpoint
- import detail endpoint
- approved-rate search endpoint
- recent imports endpoint
- a simple browser UI using real parser data
- unknown-file triage state

## Short Version

Right now we have a working deterministic parser pipeline with CLI operations and a separate UI prototype.

The next correct move is:

- not “make the LLM parse random files directly”
- not “rewrite the parser for the UI”

The next correct move is:

- turn the current parser flow into reusable services
- expose them through a thin API
- connect the UI to real parser output
- then add unknown-file handling and LLM-assisted template drafting on top
