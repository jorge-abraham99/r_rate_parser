# Repository Context

This document is the short architectural snapshot for contributors working on the freight-rate parser. It describes the implementation as it exists now. `mvp.md`, `freight_rate_scripting_phase_plan.md`, and `current_progress_and_next_steps.md` contain useful product history, but parts of them predate the connected web UI and newer parser families.

## Product Boundary

The project turns carrier rate documents into reviewable, searchable freight rates. It is deterministic and template-driven: an unknown file is rejected instead of being interpreted speculatively.

The intended trust boundary is human approval. Parsing may create run artifacts and warnings, but only approved imports are published into the searchable warehouse.

## End-to-End Flow

1. `source_registry.py` copies the source into `data/sources/raw/` and deduplicates it by checksum.
2. `inspector.py` reads workbook, CSV, or email structure and produces a small preview.
3. `template_matcher.py` scores active YAML templates. Automatic matching requires a score of at least `0.55`.
4. `services.import_source_file()` dispatches to the selected parser family.
5. The parser returns one `RateCard` plus `RateOffer`, `RateChargeLine`, and `RateNote` collections.
6. `validate.py` produces blocking errors and non-blocking warnings.
7. The run is written to `data/runs/<import_id>/`, including raw-context references, canonical JSON, validation, and review Markdown.
8. Approval publishes the detailed entities and minimal canonical rates into `data/warehouse/`.
9. Search and Rate Desk endpoints read approved warehouse rows only.

## Main Code Surfaces

- `rate_ingest/services.py`: application orchestration, import lifecycle, search, Rate Desk shaping, charge analysis, archiving, and deletion.
- `rate_ingest/models.py`: Pydantic models for sources, imports, cards, offers, charge lines, notes, validation, templates, and canonical rates.
- `rate_ingest/api.py`: FastAPI upload, import review, approval/rejection, deletion, search, and Rate Desk endpoints; also serves `UI/`.
- `rate_ingest/cli.py`: Typer wrapper over the same service layer.
- `rate_ingest/parsers/`: deterministic parser implementations.
- `data/templates/`: carrier/document-specific matching and parsing configuration.
- `UI/index.html`, `UI/app.js`: connected ingestion and source-management interface.
- `UI/rate-desk.js`: connected approved-rate comparison interface.
- `tests/test_rate_ingest_cli.py`: end-to-end CLI and API coverage using real sample documents.

## Parser Coverage

| Family | Template | Intended input |
| --- | --- | --- |
| `tabular_lane` | `msc_far_east_v1` | MSC structured lane sheets |
| `matrix` | `cosco_matrix_v1` | COSCO origin/destination matrices |
| `cosco_pdf_quote` | `cosco_pdf_quote_v1` | Text-based COSCO India/Far East door-to-quay PDF quotes |
| `offer_block` | `maersk_offer_block_v1` | Repeated Maersk offer and surcharge blocks |
| `site_to_site_rows` | `maersk_afls_site_to_site_v1` | Maersk AFLS site-to-site quote rows |
| `haulage_matrix` | `uk_haulage_matrix_v1` | UK collection-to-port haulage matrices |
| `msc_zoned_inline` | `msc_zoned_inline_v1` | MSC city/POL zones joined to Special and Tariff door-to-quay rates |
| `hapag_door_matrix` | `hapag_door_matrix_v1` | Hapag-Lloyd collection/POD door-to-quay matrix with conditional surcharges |
| `email_table` | `cma_email_table_v1` | Constrained CMA HTML tables in `.eml` files |

Adding a parser family normally requires a parser module, a dispatch branch in `parse_source_by_family()`, a YAML template, inspector recognition if the existing signals are insufficient, and a real-sample end-to-end test.

## Data Model and Outputs

The detailed model is intentionally richer than the public canonical export:

- `RateCard` describes the commercial document and shared validity/defaults.
- `RateOffer` represents a searchable lane/equipment/routing price.
- `RateChargeLine` preserves component charges and their basis.
- `RateNote` preserves commercial terms and source references.
- `CanonicalRate` exposes only rate type, raw origin/destination, amount, currency, unit, and validity.

Each run retains its parsed entities even before approval. The warehouse contains only published rows. Approving an import with a `carrier_key` archives any currently approved import using the same key and rebuilds canonical warehouse output without the archived rows.

## Rate Desk Semantics

`search_approved_offers()` joins approved cards, offers, charges, notes, and source metadata. Charge lines are grouped into origin, freight, destination, or unmatched buckets. The API exposes both quoted amounts and an `all_in_usd` comparison figure.

The USD comparison is currently indicative: `services.py` contains static demonstration rates for USD, GBP, EUR, INR, and THB. Unknown currencies currently fall back to a multiplier of `1.0`, so this must be replaced or made explicit before treating cross-currency ranking as financially authoritative.

UK haulage imports are separated from ocean results and converted into a collection-place-to-port tariff lookup. The frontend combines these tariffs with compatible ocean rates for merchant-haulage comparisons. Maersk site-to-site service modes are preserved so door and port routings can be filtered separately.

MSC zoned workbooks are carrier door-to-quay products, not standalone haulage tariffs. The parser uses each city/POL entry from the workbook's `Haulage Zones` tab to select the correct `REUDAN-SPECIAL` and `REUDAN-TARRIFF` price by normalized POL and zone, then publishes both tiers as `SD / CY` door offers. These offers remain in quote results and never enter the merchant-haulage tariff lookup. The parser also stores the two original 252-row rate tables in the run artifacts for display in the import summary. `Bristol` in the zone lookup is explicitly aliased to the rate-tab POL `PORTBURY`.

Hapag-Lloyd door-to-quay workbooks map collection locations in column C to POD headers in columns D–J, retaining the preferred POL from column B and applicable routing from row 2. Every parsed offer receives a separate USD 15 live-position charge per container; Binh Duong Terminal and Lat Krabang also receive a USD 20 emergency-fuel destination charge. The current template defaults equipment to `40HC` because the source workbook does not provide an equipment field.

COSCO India/Far East PDFs use a text-based `cosco_pdf_quote` parser. Each origin IHL row is combined with the document's Freight Rate and Emergency Fuel Surcharge for both quoted 40GP and 40HC columns. Those are the only three priced components; documentation, destination handling, and other tariff lines are excluded. The result remains an `SD / CY` carrier quote and never enters the standalone merchant-haulage lookup.

## Current Constraints

- No generic unknown-workbook parser or AI template drafting.
- No PDF/OCR path.
- Email parsing supports a narrow latest-body HTML-table shape, not arbitrary threads or attachments.
- Filesystem CSV/JSON storage has no transaction or multi-process locking layer.
- API routes have no authentication and CORS is permissive.
- Source deletion removes its run directory and published warehouse rows; callers should treat it as destructive.
- Search is substring-based for ports/providers and exact, case-insensitive matching for equipment.

## Running and Verifying

Install and test:

```bash
pip install -r requirements.txt
pytest -q
```

Start the connected application:

```bash
uvicorn rate_ingest.api:app --reload
```

Then open `http://127.0.0.1:8000/ui/`.

Tests use `RATE_INGEST_ROOT` to isolate all generated data in a temporary directory. Preserve that pattern when adding coverage so tests do not mutate the repository's real `data/warehouse/` state.
