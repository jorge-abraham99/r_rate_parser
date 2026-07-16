from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.api import app as api_app
from rate_ingest.cli import app


runner = CliRunner()
api_client = TestClient(api_app)


def seed_templates(tmp_path: Path) -> None:
    templates_dir = tmp_path / "data" / "templates"
    templates_dir.mkdir(parents=True)
    for template_path in Path("data/templates").glob("*.yaml"):
        templates_dir.joinpath(template_path.name).write_text(
            template_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def test_inspect_and_import_and_approve_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "MSC - FAR EAST RATES JAN.xlsx"
    source.write_bytes(Path("rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["inspect", str(source)])
    assert result.exit_code == 0
    assert "Likely parser family" in result.stdout

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Import created:" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    assert run_dir.joinpath("canonical_rates.json").exists()
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert canonical_rates
    assert set(canonical_rates[0].keys()) == {
        "rate_type",
        "from_raw",
        "to_raw",
        "amount",
        "currency",
        "unit",
        "valid_from",
        "valid_to",
    }

    result = runner.invoke(app, ["approve", import_id, "--approved-by", "jorge"])
    assert result.exit_code == 0
    approved_rates = (tmp_path / "data" / "warehouse" / "approved_rates.csv").read_text(encoding="utf-8")
    assert "rate_type,from_raw,to_raw,amount,currency,unit,valid_from,valid_to" in approved_rates

    result = runner.invoke(app, ["search", "--pod", "HO CHI MINH"])
    assert result.exit_code == 0
    assert "MSC" in result.stdout


def test_cosco_matrix_import_creates_canonical_rates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "COSCO FAR-EAST RATES.xlsx"
    source.write_bytes(Path("rate_sheet_files/COSCO FAR-EAST RATES.xlsx").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: cosco_matrix_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert canonical_rates
    first = canonical_rates[0]
    assert first["rate_type"] == "ocean"
    assert first["unit"] == "per_container"
    assert first["from_raw"]
    assert first["to_raw"]


def test_maersk_offer_block_import_creates_charge_lines(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "MAERSK Q-1, INDIA AND FAR-EAST.xlsx"
    source.write_bytes(Path("rate_sheet_files/MAERSK Q-1, INDIA AND FAR-EAST.xlsx").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: maersk_offer_block_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert canonical_rates
    parsed_charges = run_dir.joinpath("parsed_rate_charge_lines.csv").read_text(encoding="utf-8")
    assert "Basic Ocean Freight" in parsed_charges


def test_cma_email_import_creates_canonical_rates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "RE_ Far East Wastepaper for April - Reudan.eml"
    source.write_bytes(Path("RE_ Far East Wastepaper for April - Reudan.eml").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: cma_email_table_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert canonical_rates
    first = canonical_rates[0]
    assert first["rate_type"] == "ocean"
    assert first["from_raw"] == "ACCRINGTON"
    assert first["currency"] == "USD"
    assert "MYPKG" in first["to_raw"]


def test_api_import_approve_and_search_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    seed_templates(tmp_path)
    source_bytes = Path("rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx").read_bytes()

    response = api_client.post(
        "/api/imports",
        data={"uploaded_by": "jorge"},
        files={"file": ("MSC - FAR EAST RATES JAN.xlsx", source_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parser_family"] == "tabular_lane"
    import_id = payload["import_id"]

    detail_response = api_client.get(f"/api/imports/{import_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["summary"]["rate_offers"] > 0

    approve_response = api_client.post(f"/api/imports/{import_id}/approve", json={"approved_by": "jorge"})
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["rate_import"]["status"] == "approved"

    search_response = api_client.get("/api/search", params={"pod": "HO CHI MINH", "limit": 20})
    assert search_response.status_code == 200
    search_rows = search_response.json()
    assert search_rows
    assert any("HO CHI MINH" in (row.get("pod") or row.get("final_destination") or "") for row in search_rows)

    ui_response = api_client.get("/ui/")
    assert ui_response.status_code == 200
    assert "Reudan Rate Desk" in ui_response.text
