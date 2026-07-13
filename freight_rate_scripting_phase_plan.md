# Freight Rate Sheet Centralisation — Scripting-Phase Build Plan

## 0. Purpose

This document defines a practical scripting-phase plan for building and testing a freight rate sheet centralisation system.

The goal of this phase is not to build a polished internal SaaS product yet. The goal is to prove that messy freight pricing documents can be converted into a structured, searchable rate repository using deterministic scripts, reusable parser templates, validation rules, and human review.

This phase should answer one question:

> Can we reliably turn the real rate sheets and pricing emails the forwarder receives into structured rate offers that can be searched, reviewed, trusted, and traced back to the original source?

The scripting phase should be local-first, simple, inspectable, and easy to throw away or evolve into a proper application later.

---

## 1. Core Product Principle

Do not start by building an “AI parser for any freight document.”

Start by building:

> A deterministic freight rate ingestion pipeline with reusable parser templates, human approval, validation warnings, and a searchable local repository.

AI can be introduced later as an assistant for template creation and mapping suggestions, but it should not be the main ingestion engine during the first scripting phase.

---

## 2. What This Scripting Phase Should Prove

The prototype should prove that the system can:

1. Accept real `.xlsx` and `.eml` files.
2. Store or reference the raw source document.
3. Identify the type of pricing document.
4. Apply a known parser template.
5. Extract structured rate cards, offers, charge lines, and notes.
6. Validate the extracted data.
7. Generate a human-readable review pack.
8. Allow manual approval or rejection.
9. Publish approved data into a local searchable repository.
10. Let a user search for the latest valid rate by lane, carrier, provider, destination, equipment type, and validity date.

---

## 3. Non-Goals For This Phase

The scripting phase should intentionally avoid:

- PDF parsing
- OCR
- fully automated publishing without review
- live carrier APIs
- a customer portal
- full quote generation
- production authentication
- role-based permissions
- complex contract lifecycle management
- automatic rate optimization
- complex AI agents
- replacing the operations team’s judgment

The prototype should be boring and reliable.

---

## 4. Initial Scope

### 4.1 Input Types

Support these inputs first:

| Input Type | Status | Notes |
|---|---:|---|
| `.xlsx` | In scope | Primary target for the first parser. |
| `.xls` | Optional | Can be converted to `.xlsx` before parsing, or supported later. |
| `.eml` | In scope after Excel works | Start with simple plain text and simple HTML tables. |
| `.pdf` | Out of scope | Add only after the workflow proves value. |

### 4.2 First Parser Families

The prototype should support parser families, not one giant parser.

| Parser Family | Purpose | Example Shape |
|---|---|---|
| `tabular_lane` | Rows already represent lanes/offers. | MSC-style structured workbook. |
| `matrix` | Rows and columns form a rate matrix. | COSCO-style inland matrix. |
| `offer_block` | Repeated offer sections in one workbook. | MAERSK-style quote workbook. |
| `email_table` | Rates pasted directly into email body. | `.eml` with table in body. |

### 4.3 Recommended First Cut

For the very first working script, support only:

```text
.xlsx upload/reference
source document registration
one tabular lane template
rate_cards extraction
rate_offers extraction
rate_charge_lines extraction if columns are obvious
rate_notes extraction if notes are obvious
validation
review pack generation
manual approval
local search
```

Once the end-to-end loop works, add the other parser families.

---

## 5. Scripting Architecture

## 5.1 High-Level Flow

```text
Raw source file
    ↓
Register source document
    ↓
Inspect file structure
    ↓
Classify parser family
    ↓
Match parser template
    ↓
Run deterministic parser
    ↓
Normalize extracted data
    ↓
Validate extraction
    ↓
Generate review pack
    ↓
Human approves or rejects
    ↓
Publish approved rows to local repository
    ↓
Search approved rates
```

## 5.2 Local-First Storage

During the scripting phase, use local folders plus a lightweight local database.

Recommended structure:

```text
freight-rate-ingestion/
  README.md
  pyproject.toml
  .env.example

  data/
    sources/
      raw/
        msc_far_east_jan.xlsx
        cosco_far_east.xlsx
        maersk_q1.xlsx
        far_east_wastepaper_april.eml
      registered/
        source_documents.csv

    templates/
      msc_far_east_v1.yaml
      cosco_matrix_v1.yaml
      maersk_offer_block_v1.yaml
      email_table_basic_v1.yaml

    runs/
      import_2026_001/
        source_snapshot.json
        detected_structure.json
        parsed_rate_cards.csv
        parsed_rate_offers.csv
        parsed_rate_charge_lines.csv
        parsed_rate_notes.csv
        validation_report.json
        review.md
        approval.json

    warehouse/
      rates.duckdb
      approved_rate_cards.parquet
      approved_rate_offers.parquet
      approved_rate_charge_lines.parquet
      approved_rate_notes.parquet

  src/
    rate_ingest/
      __init__.py
      cli.py
      config.py
      models.py
      source_registry.py
      inspector.py
      classifier.py
      template_matcher.py
      parsers/
        __init__.py
        tabular_lane.py
        matrix.py
        offer_block.py
        email_table.py
      normalize.py
      validate.py
      review.py
      approve.py
      warehouse.py
      search.py
      utils.py

  tests/
    fixtures/
    golden_outputs/
    test_tabular_lane_parser.py
    test_validation.py
    test_search.py
```

---

## 6. Recommended Tech Stack For Scripting Phase

### 6.1 Runtime

Use Python.

Recommended packages:

```text
python >= 3.11
openpyxl             # direct Excel workbook inspection
pandas               # tabular operations and output previews
pydantic             # strict internal models
pyyaml               # parser template configs
duckdb               # local searchable repository
python-dateutil      # date parsing
typer                # CLI commands
rich                 # readable terminal output
beautifulsoup4       # simple HTML email parsing
lxml                 # HTML table support
pytest               # tests
```

Optional later:

```text
xlrd or libreoffice conversion  # for legacy .xls
rapidfuzz                       # fuzzy matching for headers and locations
polars                          # faster dataframe work if needed
jinja2                          # prettier review reports
```

### 6.2 Why DuckDB Locally

DuckDB is useful for the scripting phase because it can query CSV and Parquet files easily, feels close to SQL, and avoids setting up Postgres before the parsing logic is proven.

Later, the same schema can move to Supabase/Postgres.

---

## 7. Command-Line Interface

The first version should be controlled by CLI commands.

### 7.1 Inspect A Source File

```bash
python -m rate_ingest inspect data/sources/raw/msc_far_east_jan.xlsx
```

Expected output:

```text
File: msc_far_east_jan.xlsx
Type: xlsx
Sheets found: 5
Likely parser family: tabular_lane
Possible provider: MSC
Possible templates:
- msc_far_east_v1, confidence 0.91
```

Generated file:

```text
data/runs/import_xxx/detected_structure.json
```

### 7.2 Run An Import

```bash
python -m rate_ingest import data/sources/raw/msc_far_east_jan.xlsx --template msc_far_east_v1
```

Or allow auto-template selection:

```bash
python -m rate_ingest import data/sources/raw/msc_far_east_jan.xlsx --auto
```

Expected output:

```text
Import created: import_2026_001
Parser family: tabular_lane
Template used: msc_far_east_v1
Rate cards extracted: 1
Rate offers extracted: 132
Charge lines extracted: 924
Notes extracted: 8
Validation warnings: 11
Review pack: data/runs/import_2026_001/review.md
```

### 7.3 Review An Import

```bash
python -m rate_ingest review import_2026_001
```

This opens or prints the review file path.

### 7.4 Approve An Import

```bash
python -m rate_ingest approve import_2026_001 --approved-by jorge
```

This publishes the parsed rows into the local DuckDB repository.

### 7.5 Reject An Import

```bash
python -m rate_ingest reject import_2026_001 --reason "Validity dates were mapped incorrectly"
```

### 7.6 Search Approved Rates

```bash
python -m rate_ingest search \
  --origin "Bristol" \
  --pod "Mundra" \
  --equipment "40HC" \
  --valid-on 2026-04-15
```

Expected output:

```text
Found 3 approved offers

1. Provider: MSC
   Carrier: MSC
   Origin: Bristol
   POL: Southampton
   POD: Mundra
   Equipment: 40HC
   Base Amount: 360 GBP
   All-in: true
   Valid: 2026-04-01 to 2026-04-30
   Source: msc_far_east_jan.xlsx
   Import: import_2026_001
```

---

## 8. Data Model For The Scripting Phase

The prototype should use a small relational model even if stored locally as CSV/Parquet/DuckDB.

The key principle:

> Do not flatten everything into one giant normalized_rates table.

Use source documents, imports, rate cards, rate offers, charge lines, notes, and templates.

---

## 8.1 `source_documents`

Stores the raw file/email metadata.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Generated UUID. |
| `source_type` | string | yes | `xlsx`, `xls`, `eml`. |
| `file_name` | string | yes | Original filename. |
| `source_path` | string | yes | Local path in scripting phase. |
| `provider_name` | string | no | Detected or manually provided. |
| `received_at` | datetime | no | From email or file metadata if available. |
| `uploaded_by` | string | no | Local user name. |
| `checksum` | string | yes | SHA256 to detect duplicate files. |
| `status` | string | yes | `registered`, `imported`, `failed`. |
| `created_at` | datetime | yes | Registration timestamp. |

---

## 8.2 `rate_imports`

Stores each import attempt.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Generated import ID. |
| `source_document_id` | string | yes | FK-like reference. |
| `parser_family` | string | yes | `tabular_lane`, `matrix`, `offer_block`, `email_table`. |
| `template_id` | string | no | Template used, if any. |
| `classification_confidence` | number | no | 0 to 1. |
| `status` | string | yes | `parsed`, `pending_review`, `approved`, `rejected`, `failed`. |
| `validation_summary_json` | json | no | Counts by severity. |
| `approved_by` | string | no | User who approved. |
| `approved_at` | datetime | no | Approval timestamp. |
| `created_at` | datetime | yes | Import timestamp. |

---

## 8.3 `rate_cards`

Represents the commercial document or logical rate card being imported.

One workbook may produce one rate card. A complex workbook could produce multiple rate cards if it contains distinct commercial sections.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Generated UUID. |
| `rate_import_id` | string | yes | Parent import. |
| `provider_name` | string | no | Example: MSC, COSCO, Maersk, partner agent. |
| `carrier_name` | string | no | May be same as provider. |
| `document_type` | string | yes | `ocean_export`, `inland`, `quote_offer`, `surcharge_sheet`. |
| `commodity` | string | no | Example: waste paper. |
| `currency_default` | string | no | Example: GBP, USD, EUR. |
| `valid_from` | date | no | Card-level validity. |
| `valid_to` | date | no | Card-level validity. |
| `all_in_flag` | boolean/string | no | `true`, `false`, `unknown`. |
| `notes_summary` | text | no | Human-readable summary. |
| `created_at` | datetime | yes | Timestamp. |

---

## 8.4 `rate_offers`

Represents the searchable pricing unit.

A rate offer is usually a lane + equipment + amount + validity context.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Generated UUID. |
| `rate_card_id` | string | yes | Parent rate card. |
| `offer_reference` | string | no | Source offer ID or generated reference. |
| `origin` | string | no | Inland origin, pickup, or commercial origin. |
| `place_of_receipt` | string | no | If available. |
| `pol` | string | no | Port of loading. |
| `pod` | string | no | Port of discharge. |
| `final_destination` | string | no | Final destination. |
| `zone` | string | no | Haulage/inland zone. |
| `equipment_type` | string | yes | Example: `20GP`, `40HC`. |
| `service_mode` | string | no | Example: port-port, door-port. |
| `transit_time_days` | integer | no | If available. |
| `base_amount` | number | no | Main amount if available. |
| `base_currency` | string | no | Currency for base amount. |
| `all_in_flag` | boolean/string | no | Offer-level override. |
| `routing_note` | text | no | Example: `via SOU`. |
| `valid_from` | date | no | Offer-level override. |
| `valid_to` | date | no | Offer-level override. |
| `raw_sheet_name` | string | no | Excel sheet source. |
| `raw_row_reference` | string | no | Row number, cell range, or block reference. |
| `raw_row_json` | json | yes | Source row/block snapshot. |
| `created_at` | datetime | yes | Timestamp. |

---

## 8.5 `rate_charge_lines`

Stores surcharges, included charges, and breakdown rows.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Generated UUID. |
| `rate_offer_id` | string | yes | Parent offer. |
| `charge_name` | string | yes | Example: OCEAN FREIGHT, THC, BAF, GFS, FES. |
| `charge_type` | string | no | `base`, `surcharge`, `haulage`, `fee`, `unknown`. |
| `basis` | string | no | Per container, per BL, per ton, etc. |
| `amount` | number | no | Charge amount. |
| `currency` | string | no | Charge currency. |
| `included_flag` | boolean/string | no | `true`, `false`, `unknown`. |
| `source_label` | string | no | Original column or row label. |
| `raw_value` | string | no | Original cell value. |
| `created_at` | datetime | yes | Timestamp. |

---

## 8.6 `rate_notes`

Stores free-text terms, exceptions, and conditions.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Generated UUID. |
| `rate_card_id` | string | yes | Parent card. |
| `rate_offer_id` | string | no | Nullable. Use when note applies to one offer. |
| `note_type` | string | yes | `general`, `routing`, `validity`, `surcharge`, `commercial`, `free_time`, `unknown`. |
| `note_text` | text | yes | Extracted note. |
| `source_reference` | string | no | Sheet row, cell range, or email section. |
| `created_at` | datetime | yes | Timestamp. |

---

## 8.7 `parser_templates`

Stores reusable parsing rules.

During the scripting phase, parser templates can live as YAML files. Later they can move to the database.

| Field | Type | Required | Notes |
|---|---|---:|---|
| `id` | string | yes | Template ID. |
| `template_name` | string | yes | Human-readable name. |
| `provider_name` | string | no | Provider/carrier. |
| `parser_family` | string | yes | Parser family. |
| `document_type` | string | yes | Commercial document type. |
| `file_type` | string | yes | `xlsx`, `xls`, `eml`. |
| `template_config_json` | json | yes | Rules. |
| `active` | boolean | yes | Whether available for matching. |
| `created_at` | datetime | yes | Timestamp. |
| `updated_at` | datetime | yes | Timestamp. |

---

## 9. Template Design

Templates should store parser-family-specific instructions.

Do not only store column names. Real freight sheets need rules for sheet selection, skipped rows, note blocks, charge columns, default currencies, and field cleanup.

## 9.1 Example Tabular Lane Template

```yaml
template_id: msc_far_east_v1
template_name: MSC Far East Structured Lane Sheet v1
provider_name: MSC
parser_family: tabular_lane
document_type: ocean_export
file_type: xlsx
active: true

match_rules:
  filename_contains:
    - "MSC"
    - "FAR EAST"
  sheet_name_contains_any:
    - "REUDAN"
    - "PAPER"
  required_header_labels:
    - "POL"
    - "POD"
    - "FINAL DESTINATION"

sheet_rules:
  include_sheet_name_contains:
    - "REUDAN"
  exclude_sheet_name_contains:
    - "TERMS"
    - "NOTES"

header_detection:
  mode: fixed_or_search
  fixed_header_row: 1
  search_rows: 10
  multi_row_header: true

field_map:
  pol: "POL"
  pod: "POD"
  final_destination: "FINAL DESTINATION"
  equipment_type: "CONTAINER SIZE"
  base_amount: "ALL IN RATE"
  base_currency: "CURRENCY"
  valid_from: "VALID FROM"
  valid_to: "VALID TO"

breakdown_columns:
  - source_label: "OCEAN FREIGHT"
    charge_name: "Ocean Freight"
    charge_type: "base"
  - source_label: "THC"
    charge_name: "THC"
    charge_type: "surcharge"
  - source_label: "GFS"
    charge_name: "GFS"
    charge_type: "surcharge"
  - source_label: "HAUL"
    charge_name: "Haulage"
    charge_type: "haulage"

normalizers:
  equipment_type:
    "40": "40HC"
    "40HC": "40HC"
    "20": "20GP"
    "20DV": "20GP"
  currency:
    default: "GBP"

row_filters:
  skip_if_first_cell_empty: true
  skip_rows_containing:
    - "subject to"
    - "notes"
    - "validity"

note_extraction:
  scan_sheets:
    - "TERMS"
    - "NOTES"
  scan_top_rows: 20
  keywords:
    - "subject to"
    - "valid"
    - "excluding"
    - "including"
    - "free time"

validation:
  required_fields:
    - pod
    - equipment_type
    - base_amount
  amount_min: 1
  amount_max: 10000
```

---

## 10. Parser Family Specifications

## 10.1 Tabular Lane Parser

### Use Case

Use when each row already represents a lane or rate offer.

### Expected Input Shape

```text
POL | POD | FINAL DESTINATION | EQUIPMENT | ALL IN RATE | CURRENCY | THC | GFS | HAUL
```

### Steps

1. Load workbook with `openpyxl`.
2. Select sheets using template `sheet_rules`.
3. Detect header row or use fixed row.
4. Normalize headers.
5. Map source columns to canonical fields.
6. Iterate rows after header.
7. Skip empty or non-commercial rows.
8. Create one `rate_card` for the workbook or sheet.
9. Create one `rate_offer` per valid row/equipment combination.
10. Create `rate_charge_lines` for mapped breakdown columns.
11. Extract notes from configured cells/sheets.
12. Validate output.
13. Generate review pack.

### Important Edge Cases

- Multi-row headers
- Merged cells
- Blank cells that inherit previous section labels
- Notes mixed into table rows
- Amount cells with currency symbols
- Equipment labels like `40`, `40HC`, `40'`, `FEU`
- All-in rate plus breakdown columns in same sheet

---

## 10.2 Matrix Parser

### Use Case

Use when rows and columns form a matrix, and each cell contains a rate.

### Expected Input Shape

```text
Origin      | Southampton | London Gateway | Felixstowe
Bristol     | 360 via SOU | 375 via LGP    | 390
Manchester  | 420         | 435            | 450 via FXT
```

### Steps

1. Select sheet using template rules.
2. Identify row axis, usually origin/inland location.
3. Identify column axis, usually POL/POD/destination/zone group.
4. Iterate each matrix cell.
5. Split amount from routing note.
6. Create one `rate_offer` per populated cell.
7. Attach `routing_note` if present.
8. Apply default equipment/currency/validity from template or notes.
9. Extract notes from top block and side blocks.
10. Validate missing zones, missing currency, impossible amounts.

### Cell Parsing Rule

Example:

```text
360 via SOU
```

Should become:

```json
{
  "base_amount": 360,
  "routing_note": "via SOU"
}
```

### Important Edge Cases

- Cells with `POA`, `N/A`, `-`, or blank
- Cells with more than one amount
- Notes like `via SOU`, `via LGP`, `subject to space`
- Destination groups defined above the visible header row
- Zones instead of named destinations
- Currency stated once in top notes only

---

## 10.3 Offer-Block Parser

### Use Case

Use when a workbook contains repeated offer sections rather than a normal grid.

### Expected Input Shape

```text
Offer 1-1
POL: Southampton
POD: Mundra
Validity: 01/04/2026 - 30/04/2026
Equipment: 40HC

Charge            Basis        Amount      Currency
Ocean Freight     per cntr     300         USD
THC               per cntr     120         GBP
BAF               included     -           -
```

### Steps

1. Select sheet using template rules.
2. Find block start markers such as `Offer`, `Quote`, `Route`, or configured labels.
3. Split sheet into offer blocks.
4. For each block, parse route metadata.
5. Parse validity.
6. Parse equipment.
7. Parse base amount if clearly labelled.
8. Parse charge line table inside block.
9. Create `rate_offer` for each block/equipment combination.
10. Create child `rate_charge_lines`.
11. Attach block-level notes.
12. Validate that each offer has route + equipment + at least one amount or charge line.

### Important Edge Cases

- Multiple equipment types in one offer block
- Multiple currencies in one block
- Surcharge lines without base amount
- Validity inherited from top of sheet
- Offer blocks with inconsistent labels
- Repeated text sections that look like offers but are actually notes

---

## 10.4 Email Table Parser

### Use Case

Use when rates arrive pasted directly into the email body.

### First Version Scope

Only support:

- uploaded `.eml` files
- most recent email body only
- plain text tables
- simple HTML tables
- one pricing table per email

Do not support full thread history parsing yet.

### Steps

1. Parse `.eml` file.
2. Extract sender, recipients, subject, sent date.
3. Extract the most recent body section.
4. Prefer HTML body if it contains `<table>`.
5. Otherwise use plain text body.
6. Detect simple tables.
7. Map columns using a basic template or user-provided mapping.
8. Extract notes from surrounding text.
9. Create source document, rate card, offers, notes.
10. Validate and generate review pack.

### Important Edge Cases

- Forwarded messages
- Reply chains
- Signatures
- Disclaimers
- Old rates lower in the thread
- Broken plain text alignment
- Multiple tables in one email

---

## 11. Normalization Rules

Normalization should happen after parsing and before validation.

## 11.1 Equipment Normalization

Create a standard equipment vocabulary.

| Raw Value | Normalized |
|---|---|
| `20` | `20GP` |
| `20FT` | `20GP` |
| `20DV` | `20GP` |
| `40` | `40GP` or `40HC`, depending on template default |
| `40HC` | `40HC` |
| `40HQ` | `40HC` |
| `FEU` | `40HC` or `40GP`, depending on template default |

If ambiguous, preserve raw value and create a validation warning.

## 11.2 Currency Normalization

Accepted format:

```text
GBP
USD
EUR
```

Rules:

- Strip currency symbols from amount fields.
- Use template default only if explicit.
- If no currency is found and no default is configured, create a warning.
- Do not guess currency silently.

## 11.3 Amount Normalization

Examples:

| Raw | Normalized |
|---|---:|
| `£360` | `360` |
| `360 via SOU` | `360` plus note `via SOU` |
| `1,250.00` | `1250.00` |
| `POA` | null plus note or warning |
| `N/A` | null |

## 11.4 Location Normalization

Start with a simple alias file.

```yaml
locations:
  Southampton:
    aliases:
      - SOU
      - Soton
      - Southampton Port
  London Gateway:
    aliases:
      - LGP
      - London Gateway Port
  Felixstowe:
    aliases:
      - FXT
      - Felixstowe Port
```

During the scripting phase, do not overbuild master data. But do create an alias layer early because search quality depends on it.

## 11.5 Date Normalization

Rules:

- Parse dates with `dateutil`.
- Keep original raw text in `raw_row_json` or note fields.
- Use template-level validity if row-level validity is absent.
- If multiple validity ranges are found, warn instead of guessing.
- If `valid_to < valid_from`, block approval.

---

## 12. Validation Specification

Validation should produce structured warnings and errors.

Use severity levels:

```text
ERROR    Blocks approval
WARNING  Allows approval but must be shown
INFO     Informational only
```

## 12.1 Structural Validation

| Rule | Severity | Description |
|---|---|---|
| `no_offers_extracted` | ERROR | Parser produced no usable rate offers. |
| `missing_equipment_type` | ERROR or WARNING | Depends on document type. |
| `missing_amount` | WARNING | Could be valid if charge lines exist. |
| `missing_currency` | WARNING | Unless template has explicit default. |
| `invalid_date` | ERROR | Date cannot be parsed. |
| `valid_to_before_valid_from` | ERROR | Validity range is impossible. |
| `missing_route` | WARNING | No useful lane fields found. |
| `empty_source_reference` | WARNING | Offer cannot be traced to row/cell/block. |

## 12.2 Business Validation

| Rule | Severity | Description |
|---|---|---|
| `amount_outside_template_range` | WARNING | Amount is unusually low or high. |
| `duplicate_offer` | WARNING | Same lane/equipment/validity appears more than once. |
| `all_in_breakdown_conflict` | WARNING | All-in rate does not reconcile with breakdown. |
| `extra_charges_in_notes` | WARNING | Notes mention charges not captured as charge lines. |
| `zone_missing` | WARNING | Matrix/rate depends on zone but zone is blank. |
| `currency_defaulted` | INFO | Currency was defaulted from template. |
| `note_split_from_amount` | INFO | Example: `360 via SOU`. |

## 12.3 Validation Output Format

```json
{
  "import_id": "import_2026_001",
  "summary": {
    "errors": 0,
    "warnings": 7,
    "info": 12
  },
  "items": [
    {
      "severity": "WARNING",
      "rule_id": "missing_currency",
      "entity_type": "rate_offer",
      "entity_id": "offer_123",
      "message": "Currency missing; defaulted to GBP from template.",
      "source_reference": "Sheet REUDAN-PAPER row 42"
    }
  ]
}
```

---

## 13. Review Pack Specification

Every import should generate a review pack.

First version can be a Markdown file:

```text
data/runs/import_2026_001/review.md
```

Later it can become a web UI.

## 13.1 Review Pack Sections

```markdown
# Import Review: import_2026_001

## Source
- File: MSC - FAR EAST RATES JAN.xlsx
- Type: xlsx
- Provider: MSC
- Checksum: ...

## Parser
- Parser family: tabular_lane
- Template: msc_far_east_v1
- Classification confidence: 0.91

## Extraction Summary
- Rate cards: 1
- Rate offers: 132
- Charge lines: 924
- Notes: 8

## Validation Summary
- Errors: 0
- Warnings: 11
- Info: 28

## Validation Warnings
| Severity | Rule | Message | Source |
|---|---|---|---|

## Rate Offer Preview
| Origin | POL | POD | Destination | Equipment | Base Amount | Currency | Valid From | Valid To | Source |
|---|---|---|---|---|---:|---|---|---|---|

## Charge Line Preview
| Offer Ref | Charge | Amount | Currency | Included | Source |
|---|---|---:|---|---|---|

## Notes Preview
| Type | Text | Source |
|---|---|---|

## Approval Decision
- Approve command:
  python -m rate_ingest approve import_2026_001 --approved-by <name>

- Reject command:
  python -m rate_ingest reject import_2026_001 --reason "<reason>"
```

## 13.2 Review Pack Design Goal

The reviewer should be able to answer:

1. What file did this come from?
2. What parser/template was used?
3. How many offers were extracted?
4. What warnings exist?
5. What rows will be published if approved?
6. Can every published rate be traced back to a source row, cell, block, or email section?

---

## 14. Approval Workflow

During scripting, approval can be a CLI action.

Approval should:

1. Check that the import has no `ERROR` validation items.
2. Write `approval.json` to the import run folder.
3. Mark the import as approved.
4. Append or upsert approved rows into DuckDB/Parquet.
5. Preserve the raw parsed output unchanged.

Example `approval.json`:

```json
{
  "import_id": "import_2026_001",
  "decision": "approved",
  "approved_by": "jorge",
  "approved_at": "2026-07-13T22:10:00+01:00",
  "notes": "Looks correct. Currency defaults checked."
}
```

Rejected imports should also be logged.

---

## 15. Search Specification

Search is the business value layer.

## 15.1 Search Inputs

The CLI should support filters for:

```text
provider_name
carrier_name
origin
place_of_receipt
pol
pod
final_destination
zone
equipment_type
commodity
valid_on
document_type
all_in_flag
```

## 15.2 Search Logic

Basic logic:

```sql
SELECT *
FROM approved_rate_offers offers
JOIN approved_rate_cards cards ON cards.id = offers.rate_card_id
WHERE
  (:pod IS NULL OR offers.pod ILIKE :pod)
  AND (:equipment_type IS NULL OR offers.equipment_type = :equipment_type)
  AND (:valid_on IS NULL OR :valid_on BETWEEN COALESCE(offers.valid_from, cards.valid_from)
                                      AND COALESCE(offers.valid_to, cards.valid_to))
ORDER BY
  COALESCE(offers.valid_to, cards.valid_to) DESC,
  cards.provider_name ASC;
```

## 15.3 Search Result Display

Each result should show:

```text
Provider
Carrier
Origin / POL / POD / Final Destination
Equipment
Base amount
Currency
All-in flag
Validity window
Routing note
Top charge lines
Notes summary
Source file
Import ID
Raw source reference
```

## 15.4 Search Output Options

Support:

```bash
python -m rate_ingest search --pod Mundra --equipment 40HC
python -m rate_ingest search --pod Mundra --equipment 40HC --format table
python -m rate_ingest search --pod Mundra --equipment 40HC --format csv > results.csv
python -m rate_ingest search --pod Mundra --equipment 40HC --include-charges
```

---

## 16. Testing Strategy

The parser should be tested with golden outputs.

## 16.1 Golden File Testing

For each sample input file, store expected output snapshots.

```text
tests/golden_outputs/
  msc_far_east_v1/
    expected_rate_cards.csv
    expected_rate_offers.csv
    expected_rate_charge_lines.csv
    expected_rate_notes.csv
    expected_validation_summary.json
```

Then test:

```bash
pytest tests/test_tabular_lane_parser.py
```

## 16.2 What To Test

Test the following:

| Area | Test |
|---|---|
| Source registry | Duplicate file checksum detection. |
| Template matching | Correct template selected for known file. |
| Header detection | Correct row and columns found. |
| Field mapping | Canonical fields populated correctly. |
| Amount parsing | Currency symbols and notes split correctly. |
| Matrix parsing | Cell values like `360 via SOU` split correctly. |
| Offer-block parsing | Blocks identified and charge lines attached. |
| Validation | Errors/warnings generated as expected. |
| Approval | Approved rows written to warehouse. |
| Search | Query returns correct approved offer. |

## 16.3 Regression Rule

Once a sample file is working, it should never silently break.

Every parser template should have at least one test fixture and one expected output set.

---

## 17. Step-By-Step Build Plan

## Phase A — Project Skeleton

### Objective

Create the local project structure and CLI shell.

### Deliverables

- Python project initialized.
- Folder structure created.
- CLI command group created.
- Empty commands for `inspect`, `import`, `review`, `approve`, `reject`, and `search`.
- Config loader for YAML templates.

### Exit Criteria

Running this works:

```bash
python -m rate_ingest --help
python -m rate_ingest inspect --help
python -m rate_ingest import --help
```

---

## Phase B — Source Registry

### Objective

Register every source file before parsing.

### Deliverables

- Calculate file checksum.
- Store file metadata in `source_documents.csv` or DuckDB.
- Detect duplicate files.
- Create import run folder.
- Save `source_snapshot.json`.

### Exit Criteria

Running this:

```bash
python -m rate_ingest inspect data/sources/raw/msc_far_east_jan.xlsx
```

Produces:

```text
source_documents.csv updated
run folder created
source_snapshot.json created
```

---

## Phase C — Workbook Inspector

### Objective

Inspect Excel files without fully parsing them.

### Deliverables

- List sheet names.
- Capture sheet dimensions.
- Extract top N rows from each sheet.
- Detect likely header rows.
- Detect likely provider from filename/sheet/cell values.
- Save `detected_structure.json`.

### Exit Criteria

The inspector can show enough information to decide whether a workbook looks like tabular, matrix, or offer-block format.

---

## Phase D — Template Loader And Matcher

### Objective

Load YAML parser templates and choose the best match.

### Deliverables

- Template schema using Pydantic.
- Load templates from `data/templates`.
- Score templates against detected workbook structure.
- Return best template and confidence.

### Exit Criteria

Known MSC-style file gets matched to `msc_far_east_v1` with high confidence.

---

## Phase E — Tabular Lane Parser

### Objective

Implement the first deterministic parser.

### Deliverables

- Sheet selection.
- Header detection.
- Column mapping.
- Row iteration.
- Rate card creation.
- Rate offer creation.
- Charge line creation.
- Notes extraction.
- Raw row references.

### Exit Criteria

The script can parse one real structured workbook into:

```text
parsed_rate_cards.csv
parsed_rate_offers.csv
parsed_rate_charge_lines.csv
parsed_rate_notes.csv
```

---

## Phase F — Normalization Layer

### Objective

Clean values into canonical forms.

### Deliverables

- Equipment normalization.
- Currency normalization.
- Amount parsing.
- Date parsing.
- Basic location alias matching.
- Preservation of raw values.

### Exit Criteria

Common messy values are cleaned consistently, while ambiguous values are preserved and warned.

---

## Phase G — Validation Layer

### Objective

Make the extraction reviewable and safe.

### Deliverables

- Structural validation rules.
- Business validation rules.
- Severity levels.
- `validation_report.json`.
- Human-readable warning messages.

### Exit Criteria

Bad imports produce clear warnings or blocking errors.

---

## Phase H — Review Pack Generator

### Objective

Generate a review artifact for each import.

### Deliverables

- `review.md` for every import.
- Extraction summary.
- Warning summary.
- Offer preview.
- Charge line preview.
- Notes preview.
- Approval/rejection commands.

### Exit Criteria

A human can review `review.md` and understand whether the import is safe to approve.

---

## Phase I — Approval And Warehouse Publishing

### Objective

Move approved data into a searchable local repository.

### Deliverables

- Approval command.
- Rejection command.
- Approval metadata.
- DuckDB tables or Parquet outputs.
- Append approved rate cards/offers/charges/notes.

### Exit Criteria

Approved imports become queryable; rejected imports do not.

---

## Phase J — Search CLI

### Objective

Prove the business value: one place to search approved rates.

### Deliverables

- Search by provider, carrier, POL, POD, origin, destination, zone, equipment, valid date.
- Output as terminal table.
- Optional CSV export.
- Option to include charge lines and notes.

### Exit Criteria

A user can answer:

```text
What is the latest approved 40HC rate to Mundra?
Which provider sent it?
What charges are included?
Which original file did it come from?
```

---

## Phase K — Matrix Parser

### Objective

Add COSCO-style matrix support.

### Deliverables

- Matrix axis detection.
- Cell parsing.
- Amount/routing note splitting.
- Zone/destination mapping.
- Matrix-specific validation.

### Exit Criteria

Cells like `360 via SOU` become structured offers with amount and routing note.

---

## Phase L — Offer-Block Parser

### Objective

Add MAERSK-style repeated offer block support.

### Deliverables

- Block marker detection.
- Route metadata parsing.
- Validity parsing.
- Charge table parsing.
- Offer/charge line relationships.

### Exit Criteria

Each offer block becomes one or more rate offers with child charge lines.

---

## Phase M — Email Table Parser

### Objective

Support rates pasted into `.eml` email bodies.

### Deliverables

- `.eml` metadata extraction.
- Simple HTML table detection.
- Plain text table detection.
- Basic email note extraction.
- Source traceability to email subject/date/body section.

### Exit Criteria

A simple pricing email body can be converted into reviewable structured rate offers.

---

## Phase N — AI-Assisted Template Drafting

### Objective

Use AI only after deterministic parsing and review workflow are working.

### Deliverables

- AI prompt that receives detected workbook structure, sheet samples, and desired schema.
- AI returns draft template YAML/JSON.
- Human reviews and edits draft template.
- Approved template is saved to `data/templates`.
- No rates are published directly by AI.

### Exit Criteria

For an unknown workbook, AI can produce a useful first draft template that reduces manual setup time.

---

## 18. AI-Assisted Template Drafting Specification

AI should never be asked to “extract and publish all rates.”

Instead, AI should be asked:

> Given this workbook structure and sample rows, propose a parser family, header row, field map, charge columns, note extraction rules, and validation assumptions.

## 18.1 AI Input

Send only a controlled sample:

```json
{
  "file_name": "carrier_rates.xlsx",
  "sheet_summaries": [
    {
      "sheet_name": "Rates",
      "dimensions": "80 rows x 20 columns",
      "top_rows": [
        ["POL", "POD", "Destination", "40HC", "Currency"],
        ["Southampton", "Mundra", "Mundra", "360", "GBP"]
      ]
    }
  ],
  "canonical_fields": [
    "pol",
    "pod",
    "final_destination",
    "equipment_type",
    "base_amount",
    "base_currency",
    "valid_from",
    "valid_to"
  ]
}
```

## 18.2 AI Output

AI should return draft template config:

```json
{
  "parser_family": "tabular_lane",
  "confidence": 0.82,
  "template_name": "draft_carrier_rates_v1",
  "field_map": {
    "pol": "POL",
    "pod": "POD",
    "final_destination": "Destination",
    "base_amount": "40HC",
    "base_currency": "Currency"
  },
  "warnings": [
    "No explicit valid_from column found",
    "Equipment appears to be represented as amount columns"
  ]
}
```

## 18.3 AI Safety Rules

- AI can propose mappings.
- AI can propose notes.
- AI can propose parser family.
- AI can propose template rules.
- AI cannot approve imports.
- AI cannot silently default commercial values.
- AI cannot overwrite deterministic templates without human approval.
- AI output must be validated like any other template.

---

## 19. Key Risks And Controls

| Risk | Why It Matters | Control |
|---|---|---|
| Overbuilding schema | Slows down learning. | Keep core tables but allow `raw_row_json` and metadata fields. |
| PDF/OCR scope creep | Can consume the whole project. | Explicitly exclude from scripting phase. |
| AI hallucination | Commercial rates cannot be guessed. | AI proposes templates only; no auto-publish. |
| Hidden surcharges | Wrong quote comparisons. | Store charge lines and notes separately. |
| All-in vs base-rate confusion | Could make one carrier look cheaper incorrectly. | Explicit `all_in_flag` and validation warnings. |
| Location aliases | Search may miss valid rates. | Add simple alias mapping early. |
| Validity overlaps | Old rates may appear current. | Search by valid date and later add supersession handling. |
| Email threads | Old quoted rates may be parsed accidentally. | Parse most recent body only in first version. |
| Template brittleness | Carrier formats change. | Golden tests and review warnings. |
| Human review burden | If too manual, users will not adopt. | Review mappings and warnings, not every row. |

---

## 20. Definition Of Done For Scripting Phase

The scripting phase is complete when:

1. At least one real structured Excel rate sheet can be parsed end-to-end.
2. Raw source metadata is stored.
3. Extracted rate cards, offers, charge lines, and notes are generated.
4. Validation warnings are generated.
5. A review pack is generated.
6. A user can approve or reject the import.
7. Approved rates are searchable locally.
8. Every approved rate links back to source file and row/block reference.
9. There is at least one golden test preventing parser regression.
10. The team can decide which parser family to build next based on value.

---

# Full Roadmap

## Roadmap Stage 1 — Local Scripting Foundation

### Goal

Build the minimum local pipeline needed to inspect, parse, review, approve, and search one real rate sheet.

### Main Deliverables

- Python project
- CLI
- source file registry
- workbook inspector
- YAML template loader
- tabular lane parser
- local output files
- validation report
- review markdown
- approval command
- DuckDB search

### Success Criteria

One real MSC-style workbook can go from raw file to approved searchable rates.

---

## Roadmap Stage 2 — First Real Carrier Template Pack

### Goal

Support a small number of recurring supplier/carrier formats with deterministic templates.

### Main Deliverables

- 3 to 5 tabular templates
- golden tests for each template
- better header detection
- better note extraction
- improved review pack

### Success Criteria

The prototype can process several recurring formats without code changes, only template selection.

---

## Roadmap Stage 3 — Matrix Parser

### Goal

Handle inland/matrix-style sheets where rates are stored in cell intersections.

### Main Deliverables

- matrix parser family
- matrix template format
- amount/note cell splitting
- zone/destination mapping
- matrix validation rules

### Success Criteria

COSCO-style matrix rates become searchable offers with routing notes preserved.

---

## Roadmap Stage 4 — Offer-Block Parser

### Goal

Handle quote workbooks made of repeated offer blocks and surcharge tables.

### Main Deliverables

- block detection
- offer metadata parser
- charge table parser
- block-level note extraction
- offer-block validation rules

### Success Criteria

MAERSK-style quote workbooks become structured offers with child charge lines.

---

## Roadmap Stage 5 — Email Body Parser

### Goal

Handle rates sent directly in email body text or simple HTML tables.

### Main Deliverables

- `.eml` parser
- sender/date/subject metadata extraction
- simple HTML table parser
- plain text table parser
- email note extraction
- thread-history guardrails

### Success Criteria

A basic pricing email can be imported, reviewed, approved, and searched.

---

## Roadmap Stage 6 — Local Review UI

### Goal

Move from Markdown review files to a lightweight browser-based review experience.

### Main Deliverables

- simple FastAPI app or Streamlit app
- upload screen
- import review screen
- warnings panel
- extracted offers table
- charge lines table
- notes table
- approve/reject buttons

### Success Criteria

A non-technical user can review and approve imports without using CLI commands.

---

## Roadmap Stage 7 — AI-Assisted Template Creation

### Goal

Use AI to reduce setup time for new formats while preserving human control.

### Main Deliverables

- AI template proposal prompt
- structured AI output schema
- draft template review UI
- template validation
- template save/reuse workflow

### Success Criteria

For a new unknown workbook, AI produces a draft template that a human can approve or edit.

---

## Roadmap Stage 8 — Supabase/Postgres Migration

### Goal

Move from local DuckDB/Parquet into a real shared database.

### Main Deliverables

- Supabase schema
- object storage for raw sources
- migration scripts
- import history tables
- approved rates tables
- parser templates table
- row-level source traceability

### Success Criteria

Approved rates are stored centrally and can be accessed by a web app.

---

## Roadmap Stage 9 — Internal Web App

### Goal

Turn the prototype into an internal operational tool.

### Main Deliverables

- authentication
- upload page
- import queue
- review page
- search page
- source document viewer
- template management page
- approval history

### Success Criteria

Ops users can upload, review, approve, and search rates from one internal app.

---

## Roadmap Stage 10 — Email Inbox Integration

### Goal

Automatically detect rate sheets and pricing emails from a shared inbox.

### Main Deliverables

- shared inbox connection
- attachment detection
- `.xlsx` and `.eml` ingestion
- import draft creation
- notification when review is needed

### Success Criteria

New rate sheets received by email automatically appear in the import review queue.

---

## Roadmap Stage 11 — Rate Versioning And Supersession

### Goal

Make the repository safer for commercial use by handling overlapping and replacement rates.

### Main Deliverables

- active/inactive status
- superseded_by relationship
- overlap detection
- latest-valid-rate logic
- import comparison against previous rates
- unusual movement warnings

### Success Criteria

Users can trust that search results prioritize the latest valid approved rates and flag conflicts.

---

## Roadmap Stage 12 — Advanced Search And Quote Support

### Goal

Turn the repository into a quoting support tool without becoming a full TMS.

### Main Deliverables

- lane search
- rate comparison by carrier/provider
- all-in vs base breakdown display
- surcharge expansion
- quote-ready export
- CSV/Excel output

### Success Criteria

Ops can use the system to support quoting decisions faster than opening old spreadsheets manually.

---

## Roadmap Stage 13 — PDF/OCR Exploration

### Goal

Only after Excel/email workflow is proven, explore PDF ingestion.

### Main Deliverables

- PDF table extraction experiments
- OCR fallback experiments
- confidence scoring
- strict review requirements

### Success Criteria

PDF support is added only for document types where extraction quality is good enough to review safely.

---

## Roadmap Stage 14 — Production Hardening

### Goal

Make the system reliable enough for daily operational use.

### Main Deliverables

- audit logs
- user roles
- backups
- error monitoring
- template versioning
- import retry logic
- stronger tests
- deployment pipeline

### Success Criteria

The system can be used by the team without developer supervision.

---

## Final Target State

The mature product should become:

> An internal freight rate ingestion and search system that receives messy carrier, partner, and email-based pricing documents, converts them into structured rate cards and offers, preserves surcharges and notes, validates the extraction, requires approval before publishing, and lets the team search trusted rates from one place.

The scripting phase is the proof that this is possible.

