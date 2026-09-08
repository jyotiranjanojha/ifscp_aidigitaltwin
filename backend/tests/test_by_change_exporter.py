from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.by_change_exporter import build_by_patch_archive  # noqa: E402
from main import app  # noqa: E402


def test_build_by_patch_archive_outputs_only_modified_tables_and_manifest() -> None:
    baseline = {
        "sourcing": pd.DataFrame([
            {"ITEM": "A", "SOURCE": "S", "DEST": "D", "EFF": "01-01-1970", "DISC": "01-01-1970", "FACTOR": 1}
        ]),
        "sku": pd.DataFrame([{"ITEM": "A", "LOC": "D"}]),
    }
    archive = build_by_patch_archive(
        baseline,
        [{"entity": "sourcing", "key": "A|S|D", "value": 0.25, "justification": "capacity what-if"}],
        timestamp=pd.Timestamp("2026-09-04T12:34:56").to_pydatetime(),
        scenario_id="scenario_001",
        financial_impact={"protected_revenue": 145000},
    )

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = sorted(zf.namelist())
        manifest = json.loads(zf.read("change_manifest.json"))
        instructions = zf.read("BY_UI_Instructions.txt").decode("utf-8")
        csv_lines = zf.read("if_snop_sourcing-20260904123456.csv").decode("utf-8").splitlines()

    assert names == ["BY_UI_Instructions.txt", "change_manifest.json", "if_snop_sourcing-20260904123456.csv"]
    assert manifest["scenario_id"] == "scenario_001"
    assert manifest["modified_table_count"] == 1
    assert manifest["change_count"] == 1
    assert "Screen: Supply Chain Network > Sourcing Rules" in instructions
    assert csv_lines[0] == "ITEM|SOURCE|DEST|EFF|DISC|FACTOR"
    assert csv_lines[1] == "A|S|D|19700101000000|19700101000000|0.75"


def test_export_by_patch_endpoint_returns_zip() -> None:
    client = TestClient(app)
    csv_bytes = b"ITEM|SOURCE|DEST|EFF|DISC|FACTOR\nA|S|D|01-01-1970|01-01-1970|1\n"
    response = client.post(
        "/api/v1/simulation/export-by-patch",
        data={
            "scenario_id": "scenario_endpoint",
            "scenario_deltas": json.dumps([{"entity": "sourcing", "key": "A|S|D", "value": 0.1}]),
            "financial_impact": json.dumps({"mitigation_cost": 100}),
        },
        files=[("files", ("if_snop_sourcing-20260904123456.csv", io.BytesIO(csv_bytes), "text/csv"))],
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert "change_manifest.json" in zf.namelist()
        assert "BY_UI_Instructions.txt" in zf.namelist()