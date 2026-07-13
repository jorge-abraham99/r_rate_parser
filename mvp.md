# MVP: Freight Rate Sheet Centralisation

## Recommendation

The current direction is broadly correct, but the MVP should be tightened in six important ways:

1. Start with Excel only in MVP 1. Do not include PDF or email parsing in the first build. The sample files already show enough complexity without adding OCR or email-thread handling.
2. Do not use one flat `normalized_rates` table as the core model. Freight rates have lane data, surcharge lines, validity periods, zones, and free-text conditions. A parent-child structure is a better fit.
3. Build deterministic parsers first and use AI as a fallback assistant, not as the main ingestion engine.
4. The first implementation should support one parser family only: tabular Excel rate sheets. The other sample formats should stay in the roadmap until the full upload-to-search loop works.
5. Keep the relational model, but allow `raw_row_json` and `metadata_json` fields so the team does not get stuck designing a perfect freight schema too early.
6. Add lightweight location aliasing and rate supersession early, because both directly affect search quality and trust.

## What The Sample Files Tell Us

The files in [rate_sheet_files](/Users/abraham/Documents/reudan/parser/rate_sheet_files) show at least four real input patterns:

1. `MSC - FAR EAST RATES JAN.xlsx`
This is the cleanest case. It has a structured lane sheet, a haulage zone sheet, and separate terms.

2. `COSCO FAR-EAST RATES.xlsx`
This is semi-structured. It mixes long free-text conditions at the top with a matrix-style inland table where some cells contain both amounts and routing notes like `via SOU`.

3. `MAERSK Q-1, INDIA AND FAR-EAST.xlsx`
This is not a normal rate grid. It is an offer-style quote workbook with repeated offer blocks, each with route metadata and surcharge line items.

4. `RE_ Far East Wastepaper for April - Reudan.eml`
This shows that rates can also arrive pasted directly into the email body, not only as attachments.

That means the actual product is not "parse spreadsheets". The product is:

Convert commercial freight pricing documents of different shapes into one searchable internal rate repository, while preserving source context and human control.

## Problem

The freight forwarder receives rates from multiple carriers and partners in inconsistent formats. Operations teams then need to:

* open each file or email
* understand the layout manually
* identify validity, lanes, zones, surcharges, and exceptions
* compare it to previous rates
* use that information later when quoting

This is slow, error-prone, and hard to audit. The main pain is not only extraction. The main pain is that the data is fragmented and difficult to trust later.

## MVP Goal

Build an internal tool that lets the team upload rate sheets, extract the usable rate data into a standard structure, review the extraction, and search everything in one place.

The MVP is successful if a user can answer:

* What is the latest valid rate for this lane?
* Which carrier/provider sent it?
* Is the figure all-in or broken into charges?
* What surcharges and notes apply?
* Which original file or email did this come from?

## MVP Scope

This section defines the first shippable MVP, not the full product vision.

### In Scope

* Manual upload of `.xlsx` and `.xls`
* Storage of the original source file
* One parser family: tabular lane sheets
* One or two deterministic templates for real carrier files
* Human review before publishing extracted rates
* Central searchable rate repository
* Validity tracking
* Lightweight supersession or deactivation of older rates
* Surcharge breakdown support
* Free-text note capture
* Lightweight location alias normalization
* Audit trail back to the source

### Out of Scope

* PDF and OCR ingestion
* `.eml` parsing in the first build
* Matrix-style sheet parsing in the first build
* Offer-block parsing in the first build
* Fully automatic publish-without-review
* Live carrier API integrations
* Full quote generation
* Customer-facing portal
* Contract lifecycle management
* Rate optimisation or recommendations

## User Workflow

1. User uploads a workbook.
2. System stores the raw source and creates an import record.
3. System matches the file against a known template.
4. Deterministic parsing runs.
5. System normalizes extracted data into internal entities.
6. Validation rules run and warnings are shown.
7. User reviews a preview and approves or rejects the import.
8. Approved rates become searchable in the central repository.

## Product Vision Beyond MVP 1

The sample files show that the product will eventually need multiple parser families. That is the roadmap, not the first build.

### 1. Tabular Lane Parser

This is the only parser family in MVP 1.

Use for sheets like MSC rate tabs where rows already represent lanes and columns represent fields such as POL, POD, final destination, container size, all-in amount, and charge breakdown.

### 2. Matrix Parser

Use for sheets like COSCO where:

* the first column is an origin or inland location
* the top row or top note block describes destination groups
* cell values may contain both amount and route note

Example: `360 via SOU` should become:

* amount: `360`
* routing_note: `via SOU`

### 3. Offer-Block Parser

Use for workbooks like MAERSK where one sheet contains repeated offer sections:

* route metadata
* validity
* equipment
* surcharge rows

Each offer should become one or more structured rate offers plus child charge lines.

### 4. Email Table Parser

Use for `.eml` files where the rate table is in the email body.

When this is added later, the first version should support only:

* a single uploaded `.eml`
* the most recent message body only
* plain text or simple HTML table extraction
* no thread-history parsing

## Canonical Data Model

The core mistake to avoid is flattening everything into one table. The MVP should use a small relational model, but it should stay pragmatic and flexible.

### 1. `source_documents`

Stores the original file or email.

Suggested fields:

```text
id
source_type            -- xlsx, xls, eml
file_name
storage_path
provider_name
received_at
uploaded_by
status
checksum
metadata_json
created_at
```

### 2. `rate_imports`

Stores each import attempt.

```text
id
source_document_id
parser_family
template_id
classification_confidence
status                 -- pending_review, approved, rejected, failed
validation_summary_json
match_details_json
approved_by
approved_at
created_at
```

### 3. `rate_cards`

Represents the commercial document or logical rate card being imported.

```text
id
rate_import_id
provider_name
carrier_name
document_type          -- ocean_export, inland, quote_offer
commodity
currency_default
valid_from
valid_to
pricing_model          -- all_in, base_only, breakdown_available, unknown
notes_summary
active_flag
supersedes_rate_card_id
superseded_at
metadata_json
created_at
```

### 4. `rate_offers`

Represents a search-friendly pricing unit.

```text
id
rate_card_id
offer_reference
origin
place_of_receipt
pol
pod
final_destination
zone
equipment_type
service_mode
transit_time_days
base_amount
base_currency
routing_note
raw_row_reference
raw_row_json
metadata_json
created_at
```

### 5. `rate_charge_lines`

Stores surcharge or breakdown lines per offer.

```text
id
rate_offer_id
charge_name
charge_type
basis
amount
currency
included_flag
source_label
raw_charge_json
created_at
```

### 6. `rate_notes`

Stores free-text notes, terms, and exceptions.

```text
id
rate_card_id
rate_offer_id          -- nullable
note_type              -- general, routing, validity, surcharge, commercial
note_text
metadata_json
created_at
```

### 7. `location_aliases`

This should be lightweight in MVP 1. The goal is not full geodata management. The goal is keeping search usable when carriers use different labels for the same place.

```text
id
canonical_name
alias
location_type          -- city, port, terminal, code
created_at
```

### 8. `parser_templates`

Stores reusable parsing rules.

```text
id
template_name
provider_name
parser_family
document_type
file_type
template_config_json
active
created_at
updated_at
```

## Location Normalization

Location normalization should be introduced early, even in a lightweight form.

Examples from real workflows:

* `SOU`
* `Southampton`
* `Soton`
* `FXT`
* `Felixstowe`
* `via SOU`

For MVP 1:

* store the raw label exactly as received
* map common aliases to a canonical location name
* keep routing text like `via SOU` separately from the main location field where possible

Search should use canonical names, while still showing the raw source value for traceability.

## Template Design

Templates should not only store column names. They must store parser-family-specific rules.

Example capabilities:

* sheet selection rules
* header row detection
* offer block start markers like `Offer 1-1`
* row skip rules
* field mapping
* value cleanup rules
* currency defaults
* zone lookup references
* note extraction rules

Example template shape:

```yaml
template_name: msc_far_east_v1
provider_name: MSC
parser_family: tabular_lane
sheet_rules:
  include:
    - "REUDAN-PEUTE"
    - "REUDAN-PAPER"
header_rows:
  start: 1
  end: 2
field_map:
  pol: "POL"
  pod: "POD"
  final_destination: "FINAL DESTINATION"
  equipment_type: "CONTAINER SIZE"
  base_amount: "** ALL IN RATE Subj. to ETS, FEU **"
breakdown_columns:
  - "OCEAN FREIGHT"
  - "GFS"
  - "THC"
  - "SPS"
  - "CSF"
  - "HAUL"
  - "FES"
normalizers:
  equipment_type:
    "40": "40HC"
```

## AI Role

AI is useful, but it should sit behind deterministic logic and should not be part of MVP 1.

### Use AI For

* proposing a parser family when no template matches well
* proposing field mappings for new formats
* identifying likely note blocks, validity statements, and surcharge labels
* producing a draft template config for human approval

### Do Not Use AI For

* automatically publishing rates into production
* silently transforming commercial values without validation
* replacing deterministic parsing for already-known templates

## Validity And Supersession

Validity dates alone are not enough. The system also needs a basic way to decide whether a rate is current, replaced, or overlapping.

For MVP 1:

* every approved rate card should have an `active_flag`
* a user should be able to mark an older rate card as superseded by a newer import
* the system should warn when a newly approved rate overlaps an existing active rate for the same lane, equipment type, and scope
* customer-specific or commodity-specific scope should stay attached to the rate card

This is not full contract lifecycle management. It is just enough control to keep search results trustworthy.

## Validation Rules

Before approval, the system should validate both structure and business sanity.

### Structural Validation

* required fields exist for the parser family
* at least one rate offer was extracted
* dates parse correctly
* amounts are numeric after cleanup
* currencies are present or defaulted explicitly

### Business Validation

* `valid_to` is not before `valid_from`
* amount is inside an acceptable range for that template
* duplicate offers are flagged
* all-in offers are not mixed with breakdown logic incorrectly
* breakdown sum is flagged if it clearly conflicts with all-in amount
* zone-based offers have a zone value
* notes mentioning extra charges are captured
* overlapping active rates are flagged for review

### Review Warnings Examples

* `23 offers extracted but 7 have no validity`
* `12 matrix cells contain notes like "via SOU" that were split from amount`
* `Offer 3 has surcharge lines but no base amount`
* `Currency missing; defaulted to GBP from template`

## Review UI

The MVP review screen should prioritize trust and speed, not manual row editing.

Required features:

* raw source preview
* template used
* extracted offers preview
* extracted surcharge preview
* extracted notes preview
* validation warnings
* clear pricing model per offer: `all_in`, `base_only`, `breakdown_available`, or `unknown`
* row-level or source-cell traceability back to the workbook
* approve or reject import
* ability to mark an older rate card as superseded during approval

The user should be able to answer four questions quickly:

* Do I trust this extraction?
* What did it miss or default?
* Where exactly did this value come from?
* What will become searchable if I approve?

The user should review the extraction result, not rebuild the file by hand.

## Search UI

This is the business value layer. Once data is approved, the team needs a single lookup screen.

Search filters should include:

* provider
* carrier
* origin
* POL
* POD
* final destination
* zone
* equipment type
* commodity
* valid date
* document type
* active versus superseded status

The result view should show:

* base amount
* pricing model
* surcharge breakdown if available
* routing notes
* validity window
* active or superseded status
* link back to the original source document

## Suggested Tech Approach

Keep the first version operationally simple.

### Backend

* Python with FastAPI
* `openpyxl` for workbook parsing
* Postgres for structured storage
* object storage for raw files

### Frontend

* simple internal web app
* upload page
* import review page
* search page

### Parsing Architecture

* template matcher
* tabular parser handler
* normalization layer
* validation layer
* review and approval workflow

## Delivery Plan

### MVP 1

Build one full, trustworthy workflow around tabular Excel ingestion.

Deliverables:

* upload flow for Excel files
* raw source storage
* database schema with flexible metadata fields
* one tabular parser family
* one or two real carrier templates
* location alias mapping for common ports and codes
* review and approval workflow with source traceability
* search page for approved active rates
* basic supersession handling

### MVP 2

Expand document coverage once MVP 1 works operationally.

Deliverables:

* second and third Excel parser families
* COSCO matrix parser
* MAERSK offer-block parser
* note extraction
* improved overlap detection
* basic email body parser with restricted scope

### MVP 3

Add AI only after deterministic ingestion and review work correctly.

Deliverables:

* draft template generation
* mapping review UI
* template save and reuse
* import comparison versus previous imports

## Success Criteria

MVP 1 should be considered successful if it can:

* ingest one real recurring tabular carrier format with reviewable output
* support one or two real templates reliably
* let users find approved rates in one screen
* preserve surcharge and note context
* reduce manual rate lookup and spreadsheet cleaning time materially
* let every approved rate be traced back to the source file

## Final Judgement

This is a good problem for an MVP, but only if the first version is narrower and more operationally grounded than the earlier draft.

The right first product is not an "AI parser for any freight document". The right first product is:

An internal rate ingestion and search tool with one deterministic Excel parser family, human approval before publish, source traceability, and just enough schema flexibility to learn what the business actually needs before broadening format coverage.
