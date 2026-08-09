# Freight Rate Ingest — Agent Guide

## Project
Deterministic, template-based freight rate sheet ingestion tool. **No AI API key needed**. Unknown files will not magically parse.

## Commands

| What | Command |
|---|---|
| Import a file | `python -m rate_ingest import <path>` |
| Review import | `python -m rate_ingest review <import_id>` |
| Approve | `python -m rate_ingest approve <import_id> --approved-by <name>` |
| Reject | `python -m rate_ingest reject <import_id> --reason "..."` |
| Search approved | `python -m rate_ingest search --pod "HO CHI MINH"` |
| Debug template match | `python -m rate_ingest inspect <path>` |
| Run tests | `pytest -q` |
| Dev server | `uvicorn rate_ingest.api:app --reload` then open `http://127.0.0.1:8000/ui/` |

## Entry Points
- **CLI**: `rate_ingest/__main__.py` → `cli.py` (typer)
- **API**: `rate_ingest/api.py` (FastAPI, also serves `UI/` as static files)
- **Shared logic**: `rate_ingest/services.py` — called by both CLI and API

## Parser Families (in `rate_ingest/parsers/`)
`tabular_lane` (MSC), `matrix` (COSCO), `cosco_pdf_quote` (COSCO PDF), `offer_block` (MAERSK), `site_to_site_rows` (Maersk AFLS), `haulage_matrix` (UK inland), `msc_zoned_inline` (MSC door-to-quay), `hapag_door_matrix` (Hapag-Lloyd door-to-quay), `email_table` (CMA email)

## Templates
YAML files in `data/templates/`: `msc_far_east_v1.yaml`, `msc_zoned_inline_v1.yaml`, `cosco_matrix_v1.yaml`, `cosco_pdf_quote_v1.yaml`, `hapag_door_matrix_v1.yaml`, `maersk_offer_block_v1.yaml`, `maersk_afls_site_to_site_v1.yaml`, `uk_haulage_matrix_v1.yaml`, `cma_email_table_v1.yaml`

## Data Flow
`repository/register source → inspect → classify → find_best_template → parse → validate → review → repository/approve`

Data lives at `data/runs/<import_id>/`. Approved rates go to `data/warehouse/approved_rates.csv`.

## Config
Env var `RATE_INGEST_ROOT` overrides data root (defaults to cwd). `RATE_STORAGE_BACKEND` defaults to `csv`. The Stage 4 Postgres adapter requires server-only `SUPABASE_DB_URL` and an explicit organization UUID. Tests always set the data root:
```python
monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
```

## Testing
- Tests use `typer.testing.CliRunner` and `fastapi.testclient.TestClient`
- Real files from `rate_sheet_files/` are copied into temp dirs
- Templates must be seeded: `seed_templates(tmp_path)` copies `data/templates/*.yaml`
- `models.py` defines the entity schema (RateCard / RateOffer / RateChargeLine / RateNote / CanonicalRate)
- Canonical output: `rate_type`, `from_raw`, `to_raw`, `amount`, `currency`, `unit`, `valid_from`, `valid_to`

## UI (`UI/`)
- v4 vanilla HTML/CSS/JS. No build step.
- Demo mode toggle in `UI/config.js` (`window.RATE_DESK_CONFIG.demoMode`)
- Two screens: Import (`/ui/import.html`), Quote (`/ui/`)

## Railway Deploy
- Persistent volume must be mounted at `/app/data`
- Start command: `uvicorn rate_ingest.api:app --host 0.0.0.0 --port $PORT`
- Healthcheck: `/api/health`

## Repo Structure
```
rate_ingest/         # Python package (main logic)
  parsers/           # Parser family implementations
  repositories/      # Persistence interface, CSV/Postgres adapters, mappings
  cli.py             # Typer CLI app
  api.py             # FastAPI app
  services.py        # Shared service layer
  models.py          # Pydantic models
  config.py          # Settings (file-system paths)
tests/
  test_rate_ingest_cli.py   # Parser/API integration tests
  test_auth.py              # Auth/API/UI contract tests
  test_repositories.py      # Repository parity and boundary tests
  test_postgres_repository.py              # Postgres mapping/unit tests
  test_postgres_repository_integration.py  # Explicit opt-in DB test
UI/                          # Frontend (static files, no build)
data/
  templates/                 # YAML template definitions
rate_sheet_files/            # Test fixtures (real carrier files)
```

## Gotchas
- No CI, no linter, no formatter, no typechecker configured
- Tests copy real `.xlsx`/`.eml` files — ensure paths exist
- `.eml` parser reads only the latest body, not the reply chain
- Approving a new import with the same `carrier_key` auto-archives the previous approved one
- Supabase Auth is active; rate data is still one shared CSV warehouse
- Postgres adapter exists, but the runtime backend still defaults to CSV
- Postgres integration tests require explicit opt-in and disposable organizations
