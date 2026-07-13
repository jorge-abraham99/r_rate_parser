from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.cli import app


runner = CliRunner()


def test_inspect_and_import_and_approve_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RATE_INGEST_ROOT", str(tmp_path))
    raw_dir = tmp_path / "incoming"
    raw_dir.mkdir()
    source = raw_dir / "MSC - FAR EAST RATES JAN.xlsx"
    source.write_bytes(Path("rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx").read_bytes())

    templates_dir = tmp_path / "data" / "templates"
    templates_dir.mkdir(parents=True)
    templates_dir.joinpath("msc_far_east_v1.yaml").write_text(
        Path("data/templates/msc_far_east_v1.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

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
