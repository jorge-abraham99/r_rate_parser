# Freight Rate Ingest

`rate_ingest` is a local-first scripting pipeline for turning freight rate sheets into a small canonical rate JSON/CSV output that can be reviewed, approved, and searched.

The important point is that this is not a generic AI parser and not a web product. It is a deterministic ingestion workflow:

1. take a freight rate file
2. match it to a known parser template
3. parse it into structured rows
4. generate a review pack
5. approve or reject it
6. publish only the approved canonical rates

The canonical business-facing output is this minimal shape:

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

The pipeline still keeps richer internal debug files for review, but the business-facing outputs are:

- `data/runs/<import_id>/canonical_rates.json`
- `data/warehouse/approved_rates.csv`

## Current Coverage

Currently implemented:

- `tabular_lane` for MSC-style Excel workbooks

Not implemented yet in the new CLI path:

- random unknown workbooks
- AI template drafting
- COSCO matrix parsing
- MAERSK offer-block parsing
- `.eml` parsing
- PDF parsing

## Install

```bash
pip install -r requirements.txt
```

## Normal Workflow

You usually only need four commands.

### 1. Import

This is the main entrypoint. It automatically registers the source, inspects the workbook, tries to match a known template, parses the file, validates the result, and creates a review pack.

```bash
python -m rate_ingest import "rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx"
```

At the end it prints an `import_id` and the path to the generated review pack.

### 2. Review

Read the generated review pack before publishing anything.

```bash
python -m rate_ingest review <import_id>
```

This shows:

- what file was parsed
- which template was used
- how many rows were extracted
- what warnings/errors were found
- a preview of the rows that would be published

### 3. Approve or Reject

Approve when the review output looks good:

```bash
python -m rate_ingest approve <import_id> --approved-by abraham
```

Reject when it is wrong:

```bash
python -m rate_ingest reject <import_id> --reason "mapped incorrectly"
```

Approval publishes the canonical output to the local warehouse.

### 4. Search

Search only looks at approved data.

```bash
python -m rate_ingest search --pod "HO CHI MINH"
```

## Optional Debug Command

There is also an `inspect` command, but it is not part of the normal operator flow. Use it only when you are trying to understand why a workbook did not match a template.

```bash
python -m rate_ingest inspect "rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx"
```

## What Gets Written

Each import creates a run folder:

`data/runs/<import_id>/`

Important files inside it:

- `data/runs/<import_id>/source_snapshot.json`
- `data/runs/<import_id>/detected_structure.json`
- `data/runs/<import_id>/parsed_rate_offers.csv`
- `data/runs/<import_id>/validation_report.json`
- `data/runs/<import_id>/review.md`
- `data/runs/<import_id>/canonical_rates.json`

After approval, canonical rows are appended to:

- `data/warehouse/approved_rates.csv`

Parser templates live here:

- `data/templates/msc_far_east_v1.yaml`

## Current Boundaries

- unknown/random files do not magically parse yet
- no AI template drafting yet
- no `.eml` parsing yet
- no PDF support
- COSCO/MAERSK/email parser families are still future work in this new CLI architecture

If a workbook is unseen, the intended next step is AI-assisted template drafting on top of this deterministic pipeline, not replacing the deterministic parser flow.
