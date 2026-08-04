# Freight Rate Ingest

`rate_ingest` is a local-first ingestion tool for turning freight rate files into a small canonical output that can be reviewed, approved, and searched.

This is not a generic AI parser. The current system is deterministic:

1. register a source file
2. inspect its structure
3. match it to a known template
4. parse it into structured rows
5. generate a review pack
6. approve or reject it
7. publish only approved canonical rates

There is no AI API key in the current path. A file only parses if it matches a known template and parser family.

The repo now has two operator surfaces over the same parser logic:

- CLI
- local web UI backed by FastAPI

For a concise architecture and maintenance guide, see [CONTEXT.md](CONTEXT.md).

## Canonical Output

The business-facing output is intentionally small:

```json
{
  "rate_type": "ocean",
  "from_raw": "FELIXSTOWE",
  "to_raw": "JAKARTA",
  "amount": 309,
  "currency": "USD",
  "unit": "per_container",
  "valid_from": "2026-01-01",
  "valid_to": "2026-01-31"
}
```

Each run still keeps richer debug artifacts for review, but the main outputs are:

- `data/runs/<import_id>/canonical_rates.json`
- `data/warehouse/approved_rates.csv`

## Current Coverage

Implemented parser families:

- `tabular_lane` for known MSC-style Excel workbooks
- `matrix` for known COSCO-style matrix workbooks
- `offer_block` for known MAERSK quote workbooks
- `site_to_site_rows` for known MAERSK AFLS site-to-site workbooks
- `haulage_matrix` for known UK inland-haulage Excel/CSV matrices
- `msc_zoned_inline` for MSC workbooks where a city/POL zone selects an inline haulage-and-ocean price from Special and Tariff tabs
- `email_table` for known CMA-style `.eml` emails with a top-body HTML rate table

Not implemented yet:

- random unknown workbooks
- AI template drafting
- PDF parsing
- deep email thread parsing
- attachment extraction from emails

In practice this means a random unseen file will not magically work today.

## Install

```bash
pip install -r requirements.txt
```

## CLI Workflow

### 1. Import

Workbook example:

```bash
python -m rate_ingest import "rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx"
```

Email example:

```bash
python -m rate_ingest import "RE_ Far East Wastepaper for April - Reudan.eml"
```

At the end it prints an `import_id` and the review pack path.

### 2. Review

```bash
python -m rate_ingest review <import_id>
```

### 3. Approve Or Reject

Approve:

```bash
python -m rate_ingest approve <import_id> --approved-by abraham
```

Reject:

```bash
python -m rate_ingest reject <import_id> --reason "mapped incorrectly"
```

### 4. Search

Search only uses approved data.

```bash
python -m rate_ingest search --pod "HO CHI MINH"
```

## Local Web UI

The UI is now connected to the parser workflow through a local API. It can:

- upload and import a file
- list recent imports
- open import detail and review markdown
- approve, reject, or delete imports; replacement approvals archive the previous source version
- search and compare approved rates in the Rate Desk
- combine ocean rates with approved UK haulage tariffs
- inspect origin, freight, destination, and unmatched charge groups

Run it with:

```bash
uvicorn rate_ingest.api:app --reload
```

Then open:

```text
http://127.0.0.1:8000/ui/
```

The original design prototype is still available at:

```text
http://127.0.0.1:8000/ui/Rate%20Lookup%20v1.dc.html
```

## Railway Deployment

Yes, Railway can give this app a public domain, but two setup steps are required:

- attach a persistent volume to `/app/data`
- generate a public domain in Railway Networking

The volume is required because this app stores imports, review packs, and approved-rate data on disk under `./data`.

The Railway deployment guide is here:

- [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md)

## Debug Command

`inspect` is for debugging template matching, not normal operator use.

```bash
python -m rate_ingest inspect "RE_ Far East Wastepaper for April - Reudan.eml"
```

## What Gets Written

Each import creates:

`data/runs/<import_id>/`

Important files:

- `data/runs/<import_id>/source_snapshot.json`
- `data/runs/<import_id>/detected_structure.json`
- `data/runs/<import_id>/parsed_rate_cards.csv`
- `data/runs/<import_id>/parsed_rate_offers.csv`
- `data/runs/<import_id>/parsed_rate_charge_lines.csv`
- `data/runs/<import_id>/parsed_rate_notes.csv`
- `data/runs/<import_id>/validation_report.json`
- `data/runs/<import_id>/review.md`
- `data/runs/<import_id>/canonical_rates.json`

After approval:

- `data/warehouse/approved_rate_cards.csv`
- `data/warehouse/approved_rate_offers.csv`
- `data/warehouse/approved_rate_charge_lines.csv`
- `data/warehouse/approved_rate_notes.csv`
- `data/warehouse/approved_rates.csv`

Templates live here:

- `data/templates/msc_far_east_v1.yaml`
- `data/templates/cosco_matrix_v1.yaml`
- `data/templates/maersk_offer_block_v1.yaml`
- `data/templates/maersk_afls_site_to_site_v1.yaml`
- `data/templates/uk_haulage_matrix_v1.yaml`
- `data/templates/msc_zoned_inline_v1.yaml`
- `data/templates/cma_email_table_v1.yaml`

API/backend entrypoint:

- `rate_ingest/api.py`

Connected UI entrypoint:

- `UI/index.html`

## Current Operational Boundaries

- Storage is local CSV/JSON under `data/`; production deployment therefore requires a persistent volume.
- The API is currently intended for a trusted internal environment. It has no authentication and uses permissive CORS.
- Rate Desk currency comparison uses static demonstration FX rates from `rate_ingest/services.py`, not a live FX feed.
- Template recognition is heuristic and requires a score of at least `0.55`; unknown formats fail explicitly.
- Approval is the publication boundary. When an approved import has a `carrier_key`, approving a newer import with the same key archives the previous one and removes its published warehouse rows.

## MSC Zoned Inline Rates

The `msc_zoned_inline` parser treats `ZONE` as a join key between the workbook's `Haulage Zones` sheet and both customer rate tabs:

```text
City + POL -> Zone
Zone + POL + destination + tier -> inline haulage-and-ocean rate
```

Both `SPECIAL` and `TARIFF` offers are published together. The rate is already inclusive of city-to-POL haulage, so the Rate Desk classifies it as a door-to-quay route and does not attach the separate merchant-haulage tariff. Documentation remains an additional per-bill-of-lading charge.

The import summary preserves and displays the complete 252-row workbook table for each tier before the rates are expanded into city-level quote options.

## Email Parser Boundaries

The `.eml` path is intentionally narrow:

- it reads the latest email body, not the whole reply chain
- it selects the first top-most matching HTML table
- it ignores deeper quoted-history tables as much as possible
- it assumes destination labels come from the table header row
- if the email is plain text only or structurally different, it will likely not match

## Testing Locally

Run the test suite:

```bash
pytest -q
```

Try the email sample manually through the CLI:

```bash
python -m rate_ingest import "RE_ Far East Wastepaper for April - Reudan.eml"
python -m rate_ingest review <import_id>
```

Or through the local UI:

```bash
uvicorn rate_ingest.api:app --reload
```

Then upload the same file through the browser.

If a file is unseen, the intended next phase is AI-assisted template drafting on top of this deterministic flow, not replacing it.
