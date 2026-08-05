from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.api import app as api_app
from rate_ingest.cli import app
from rate_ingest.config import Settings


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


def test_settings_seed_missing_bundled_templates_without_overwriting_existing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RATE_INGEST_ROOT", raising=False)
    template_dir = tmp_path / "data" / "templates"
    template_dir.mkdir(parents=True)
    existing = template_dir / "msc_far_east_v1.yaml"
    existing.write_text("operator-managed template", encoding="utf-8")

    settings = Settings.load(cwd=tmp_path)
    settings.ensure()

    assert existing.read_text(encoding="utf-8") == "operator-managed template"
    assert settings.templates_dir.joinpath("msc_zoned_inline_v1.yaml").exists()
    assert {
        path.name for path in settings.templates_dir.glob("*.yaml")
    } == {
        path.name for path in Path("data/templates").glob("*.yaml")
    }


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
    assert canonical_rates[0]["valid_from"] == "2025-12-01"
    assert canonical_rates[0]["valid_to"] == "2025-12-31"
    parsed_charges = run_dir.joinpath("parsed_rate_charge_lines.csv").read_text(encoding="utf-8")
    assert "Basic Ocean Freight" in parsed_charges


def test_maersk_qtmaeu_offer_block_autodetects_and_carries_material(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "QT-MAEU-50875469-0.xlsx"
    source.write_bytes(Path("rate_sheet_files/Maersk Rates - Apr to June /QT-MAEU-50875469-0.xlsx").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: maersk_offer_block_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert canonical_rates
    assert canonical_rates[0]["valid_from"] == "2026-04-01"
    assert canonical_rates[0]["valid_to"] == "2026-04-30"
    offers = [row for row in detail_rows(run_dir / "parsed_rate_offers.csv")]
    assert offers[0]["commodity"] == "WASTEPAPER"
    assert offers[0]["pol"] == "Antwerp"


def test_maersk_rate_desk_exposes_charge_analysis(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    seed_templates(tmp_path)
    source_bytes = Path("rate_sheet_files/MAERSK Q-1, INDIA AND FAR-EAST.xlsx").read_bytes()

    response = api_client.post(
        "/api/imports",
        data={"uploaded_by": "jorge"},
        files={"file": ("MAERSK Q-1, INDIA AND FAR-EAST.xlsx", source_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    import_id = response.json()["import_id"]

    detail_response = api_client.get(f"/api/imports/{import_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["charge_bucket_summary"]["matched_charge_count"] > 0
    assert detail["charge_bucket_summary"]["unmatched_charge_count"] == 0
    assert [group["key"] for group in detail["charge_bucket_summary"]["groups"]] == ["origin", "freight", "destination"]

    approve_response = api_client.post(
        f"/api/imports/{import_id}/approve",
        json={
            "approved_by": "jorge",
            "carrier_name": "Maersk",
            "carrier_key": "maersk-demo",
            "carrier_label": "Maersk Demo",
            "contract_tag": "SPOT",
        },
    )
    assert approve_response.status_code == 200

    desk_response = api_client.get("/api/rate-desk")
    assert desk_response.status_code == 200
    desk = desk_response.json()
    maersk_rate = next(
        rate
        for rate in desk["rates"]
        if rate["source_file_name"] == "MAERSK Q-1, INDIA AND FAR-EAST.xlsx"
        and rate["offer_reference"] == "Offer 2-1"
    )
    analysis = maersk_rate["charge_analysis"]
    assert maersk_rate["transit_time_days"] == 51
    assert maersk_rate["valid_from"] == "2025-12-01"
    assert maersk_rate["valid_to"] == "2025-12-31"
    assert analysis["matched_charge_count"] > 0
    assert analysis["unmatched_charge_count"] == 0
    assert analysis["total_usd"] > 0
    assert [group["key"] for group in analysis["groups"]] == ["origin", "freight", "destination"]
    assert analysis["groups"][0]["subtotal_usd"] >= 0
    assert analysis["groups"][1]["subtotal_usd"] > 0
    assert analysis["groups"][2]["subtotal_usd"] >= 0
    assert maersk_rate["all_in_usd"] == analysis["total_usd"]


def test_maersk_afls_site_to_site_import_creates_offers_and_charge_lines(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "REUDAN_E1E_E3E_WAP_Q2 2026.xlsx"
    source.write_bytes(Path("rate_sheet_files/REUDAN_E1E_E3E_WAP_Q2 2026.xlsx").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: maersk_afls_site_to_site_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert len(canonical_rates) > 1000
    first = canonical_rates[0]
    assert first["from_raw"] == "Alcester, GB"
    assert first["to_raw"] == "Bangkok, TH"
    assert first["amount"] == 450.0
    assert first["currency"] == "USD"
    parsed_charges = run_dir.joinpath("parsed_rate_charge_lines.csv").read_text(encoding="utf-8")
    assert "Documentation fee - Destination" in parsed_charges
    assert "Export Service" in parsed_charges
    offers = [row for row in detail_rows(run_dir / "parsed_rate_offers.csv")]
    assert offers[0]["commodity"] == "WASTEPAPER"


def test_maersk_afls_rate_desk_preserves_service_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    seed_templates(tmp_path)
    source_bytes = Path("rate_sheet_files/REUDAN_E1E_E3E_WAP_Q2 2026.xlsx").read_bytes()

    response = api_client.post(
        "/api/imports",
        data={"uploaded_by": "jorge"},
        files={"file": ("REUDAN_E1E_E3E_WAP_Q2 2026.xlsx", source_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    import_id = response.json()["import_id"]

    approve_response = api_client.post(
        f"/api/imports/{import_id}/approve",
        json={
            "approved_by": "jorge",
            "carrier_name": "Maersk",
            "carrier_key": "maersk-contract",
            "carrier_label": "Maersk · Contract",
            "contract_tag": "CONTRACT",
        },
    )
    assert approve_response.status_code == 200

    desk = api_client.get("/api/rate-desk").json()
    row = next(
        item
        for item in desk["rates"]
        if item.get("place_of_receipt") == "Alcester, GB" and item.get("final_destination") == "Bangkok, TH"
    )
    assert row["service_mode"] == "SD / CY"


def test_haulage_matrix_import_autodetects_and_exposes_tariffs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "Export Waste Haulage Bristol + ALL other UK POLS INC GBLGP - GBTIL - Q2 2026 VALIDITY.xlsx"
    source.write_bytes(
        Path("rate_sheet_files/Export Waste Haulage Bristol + ALL other UK POLS INC GBLGP - GBTIL - Q2 2026 VALIDITY.xlsx").read_bytes()
    )
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: uk_haulage_matrix_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id
    canonical_rates = json.loads(run_dir.joinpath("canonical_rates.json").read_text(encoding="utf-8"))
    assert canonical_rates
    assert canonical_rates[0]["rate_type"] == "inland_export"
    assert canonical_rates[0]["currency"] == "USD"
    assert canonical_rates[0]["valid_from"] == "2026-04-01"
    assert canonical_rates[0]["valid_to"] == "2026-06-30"

    approve_response = api_client.post(
        f"/api/imports/{import_id}/approve",
        json={
            "approved_by": "jorge",
            "carrier_name": "UK Inland Haulage",
            "carrier_key": "haulage-q2",
            "carrier_label": "UK Inland Haulage",
            "contract_tag": "HAUL",
        },
    )
    assert approve_response.status_code == 200

    desk = api_client.get("/api/rate-desk").json()
    assert desk["filters"]["door_pickups"]
    assert desk["haulage_currency"] == "USD"
    assert any(item["name"] == "ABBOTS BROMLEY" for item in desk["filters"]["door_pickups"])
    assert desk["haulage_tariffs"]["abbots bromley"]["felixstowe"] == 140.14
    assert desk["haulage_tariffs"]["abbots bromley"]["southampton"] == 105.21


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


def test_msc_zoned_inline_import_joins_birmingham_to_both_pols_and_tiers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "MSC - FAR EAST AUGUST.xlsx"
    source.write_bytes(Path("rate_sheet_files/MSC - FAR EAST  AUGUST.xlsx").read_bytes())
    seed_templates(tmp_path)

    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "Template used: msc_zoned_inline_v1" in result.stdout
    import_id = next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Import created:"))
    run_dir = tmp_path / "data" / "runs" / import_id

    matches = {}
    for offer in detail_rows(run_dir / "parsed_rate_offers.csv"):
        if offer["place_of_receipt"] != "Birmingham" or offer["pod"] != "SURABAYA":
            continue
        matches[(offer["offer_reference"], offer["pol"])] = offer

    assert {
        key: float(offer["base_amount"])
        for key, offer in matches.items()
    } == {
        ("SPECIAL", "FELIXSTOWE"): 650.0,
        ("SPECIAL", "LONDON GATEWAY"): 450.0,
        ("TARIFF", "FELIXSTOWE"): 665.0,
        ("TARIFF", "LONDON GATEWAY"): 465.0,
    }
    assert matches[("SPECIAL", "FELIXSTOWE")]["zone"] == "ZONE 3"
    assert matches[("SPECIAL", "LONDON GATEWAY")]["zone"] == "ZONE 2"
    assert all(offer["service_mode"] == "SD / CY" for offer in matches.values())

    tier_tables = json.loads(run_dir.joinpath("tier_rate_tables.json").read_text(encoding="utf-8"))
    assert len(tier_tables["SPECIAL"]) == 252
    assert len(tier_tables["TARIFF"]) == 252
    special_surabaya = next(
        row
        for row in tier_tables["SPECIAL"]
        if row["pol"] == "FELIXSTOWE" and row["zone"] == "ZONE 3" and "SURABAYA" in row["pod"]
    )
    assert special_surabaya["amount"] == 650.0
    assert special_surabaya["documentation"] == "GBP 30 per B/L"

    validation = json.loads(run_dir.joinpath("validation_report.json").read_text(encoding="utf-8"))
    assert validation["summary"]["errors"] == 0

    detail_response = api_client.get(f"/api/imports/{import_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["card"]["valid_from"] == "2026-08-01"
    assert detail["card"]["valid_to"] == "2026-08-31"
    assert len(detail["tier_rate_tables"]["SPECIAL"]) == 252
    assert len(detail["tier_rate_tables"]["TARIFF"]) == 252

    approve_response = api_client.post(
        f"/api/imports/{import_id}/approve",
        json={
            "approved_by": "jorge",
            "carrier_name": "MSC",
            "carrier_key": "msc-inline",
            "carrier_label": "MSC · Inline haulage",
        },
    )
    assert approve_response.status_code == 200
    search_response = api_client.get("/api/search", params={"pod": "SURABAYA", "limit": 5000})
    assert search_response.status_code == 200
    birmingham = {
        (rate["offer_reference"], rate["pol"]): rate
        for rate in search_response.json()
        if rate["place_of_receipt"] == "Birmingham"
    }
    assert birmingham[("SPECIAL", "FELIXSTOWE")]["all_in_amount"] == 680.0
    assert birmingham[("SPECIAL", "LONDON GATEWAY")]["all_in_amount"] == 480.0
    assert birmingham[("TARIFF", "FELIXSTOWE")]["all_in_amount"] == 695.0
    assert birmingham[("TARIFF", "LONDON GATEWAY")]["all_in_amount"] == 495.0

    desk_response = api_client.get("/api/rate-desk", params={"limit": 5000})
    assert desk_response.status_code == 200
    desk = desk_response.json()
    assert {"FELIXSTOWE", "LONDON GATEWAY"}.issubset(desk["filters"]["origins"])
    assert {"SURABAYA", "SEMARANG"}.issubset(desk["filters"]["destinations"])


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

    approve_response = api_client.post(
        f"/api/imports/{import_id}/approve",
        json={
            "approved_by": "jorge",
            "carrier_name": "MSC",
            "carrier_key": "msc-peute",
            "carrier_label": "MSC — PEUTE",
            "contract_tag": "PEUTE",
        },
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["rate_import"]["status"] == "approved"

    search_response = api_client.get("/api/search", params={"pod": "HO CHI MINH", "limit": 20})
    assert search_response.status_code == 200
    search_rows = search_response.json()
    assert search_rows
    assert any("HO CHI MINH" in (row.get("pod") or row.get("final_destination") or "") for row in search_rows)

    desk_response = api_client.get("/api/rate-desk")
    assert desk_response.status_code == 200
    desk = desk_response.json()
    assert desk["rates"]
    assert desk["last_refreshed"]
    assert desk["filters"]["origins"]
    assert desk["filters"]["destinations"]
    assert desk["filters"]["equipment_types"]
    assert "Paper" in desk["filters"]["materials"]
    assert desk["rates"][0]["source_file_name"] == "MSC - FAR EAST RATES JAN.xlsx"
    assert desk["rates"][0]["carrier_key"] == "msc-peute"

    imports_response = api_client.get("/api/imports")
    assert imports_response.status_code == 200
    listed_import = next(item for item in imports_response.json() if item["import_id"] == import_id)
    assert listed_import["carrier_label"] == "MSC — PEUTE"
    assert listed_import["lane_count"] > 0

    ui_response = api_client.get("/ui/")
    assert ui_response.status_code == 200
    assert "Reudan Rate Desk" in ui_response.text
    assert "Origin port (POL)" in ui_response.text
    assert "Material" in ui_response.text
    assert "Collection place" in ui_response.text
    assert "Query API" not in ui_response.text
    assert "Import Rate File" not in ui_response.text

    import_ui_response = api_client.get("/ui/import.html")
    assert import_ui_response.status_code == 200
    assert "Drop rate sheets here" in import_ui_response.text
    assert "Review parsed sheet" in import_ui_response.text
    assert "Current file" in import_ui_response.text
    assert "Contract type" in import_ui_response.text
    assert "Query API" not in import_ui_response.text

    removed_query_ui_response = api_client.get("/ui/query-api.html")
    assert removed_query_ui_response.status_code == 404

    replacement_response = api_client.post(
        "/api/imports",
        data={"uploaded_by": "priya"},
        files={"file": ("MSC - FAR EAST RATES FEB.xlsx", source_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert replacement_response.status_code == 200
    replacement_id = replacement_response.json()["import_id"]
    replacement_approval = api_client.post(
        f"/api/imports/{replacement_id}/approve",
        json={
            "approved_by": "priya",
            "carrier_name": "MSC",
            "carrier_key": "msc-peute",
            "carrier_label": "MSC — PEUTE",
            "contract_tag": "PEUTE",
        },
    )
    assert replacement_approval.status_code == 200
    statuses = {item["import_id"]: item["status"] for item in api_client.get("/api/imports").json()}
    assert statuses[import_id] == "archived"
    assert statuses[replacement_id] == "approved"
    assert {rate["source_file_name"] for rate in api_client.get("/api/rate-desk").json()["rates"]} == {
        "MSC - FAR EAST RATES FEB.xlsx"
    }

    delete_response = api_client.delete(f"/api/imports/{replacement_id}")
    assert delete_response.status_code == 200
    assert api_client.get("/api/rate-desk").json()["rates"] == []


def detail_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
