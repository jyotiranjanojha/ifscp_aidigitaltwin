"""End-to-end API scenario test covering the full digital-twin workflow:

  1. POST /upload/                      — validate 22 BY CSV files
  2. POST /run-simulation/              — dual-solver compare (heuristic + lp)
  3. GET  /api/v1/simulation/network-graph/{sid}  — React Flow payload
  4. POST /api/v1/simulation/export-by-patch       — downloadable .zip

All tests build synthetic data in-memory; no external BY data directory required.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app  # noqa: E402
from schema_config import REQUIRED_COLUMNS_BY_ENTITY  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

TIMESTAMP = "20260910120000"

# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _ts(entity: str) -> str:
    return f"if_snop_{entity}-{TIMESTAMP}.csv"


def _sourcing_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "SRC1", "DEST": "D1", "SOURCING": "S1",
         "TRANSMODE": "TRUCK", "EFF": "01-01-1970", "DISC": "12-31-2099",
         "PRIORITY": 1, "FACTOR": 1.0, "BASE_COST": 2.5,
         "MAX_CAPACITY": 500.0, "TRANSPORT_TIME": 2, "MIN_CAPACITY": 0},
        {"ITEM": "ITEM_A", "SOURCE": "SRC2", "DEST": "D1", "SOURCING": "S2",
         "TRANSMODE": "RAIL", "EFF": "01-01-1970", "DISC": "12-31-2099",
         "PRIORITY": 2, "FACTOR": 1.0, "BASE_COST": 4.0,
         "MAX_CAPACITY": 300.0, "TRANSPORT_TIME": 5, "MIN_CAPACITY": 0},
        {"ITEM": "ITEM_B", "SOURCE": "SRC1", "DEST": "D2", "SOURCING": "S3",
         "TRANSMODE": "TRUCK", "EFF": "01-01-1970", "DISC": "12-31-2099",
         "PRIORITY": 1, "FACTOR": 1.0, "BASE_COST": 3.0,
         "MAX_CAPACITY": 400.0, "TRANSPORT_TIME": 3, "MIN_CAPACITY": 0},
    ])


def _sku_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 600.0, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D2", "DEMAND": 200.0, "PRIORITY": 1},
    ])


def _locations_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"LOC": "SRC1", "DESCR": "Supplier 1", "LOC_TYPE": "SUP",
         "U_PLANMODULE": "SUPPLY", "LATITUDE": 40.0, "LONGITUDE": -74.0},
        {"LOC": "SRC2", "DESCR": "Supplier 2", "LOC_TYPE": "SUP",
         "U_PLANMODULE": "SUPPLY", "LATITUDE": 34.0, "LONGITUDE": -118.0},
        {"LOC": "D1", "DESCR": "DC East", "LOC_TYPE": "DC",
         "U_PLANMODULE": "DC", "LATITUDE": 41.0, "LONGITUDE": -87.0},
        {"LOC": "D2", "DESCR": "DC West", "LOC_TYPE": "DC",
         "U_PLANMODULE": "DC", "LATITUDE": 37.0, "LONGITUDE": -122.0},
    ])


def _items_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "DESCR": "Widget Alpha"},
        {"ITEM": "ITEM_B", "DESCR": "Widget Beta"},
    ])


def _network_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"SOURCE": "SRC1", "DEST": "D1", "TRANSLEADTIME": 2, "LEAD_TIME": 2},
        {"SOURCE": "SRC2", "DEST": "D1", "TRANSLEADTIME": 5, "LEAD_TIME": 5},
        {"SOURCE": "SRC1", "DEST": "D2", "TRANSLEADTIME": 3, "LEAD_TIME": 3},
    ])


def _res_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"RES": "RES1", "LOC": "D1", "CAPACITY": 24, "EFFICIENCY": 1.0,
         "RESOURCE": "RES1"},
        {"RES": "RES2", "LOC": "D2", "CAPACITY": 24, "EFFICIENCY": 1.0,
         "RESOURCE": "RES2"},
    ])


def _bom_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "SUBORD": "COMP_X", "LOC": "D1", "DRAWQTY": 2.0},
        {"ITEM": "ITEM_B", "SUBORD": "COMP_Y", "LOC": "D2", "DRAWQTY": 1.5},
    ])


def _productionmethod_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "PRODUCTIONMETHOD": "PM_A1",
         "LEADTIME": 1, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D2", "PRODUCTIONMETHOD": "PM_B1",
         "LEADTIME": 2, "PRIORITY": 1},
    ])


def _productionstep_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "PRODUCTIONMETHOD": "PM_A1",
         "STEPNUM": 1, "RES": "RES1", "PRODDUR": 0.5},
        {"ITEM": "ITEM_B", "LOC": "D2", "PRODUCTIONMETHOD": "PM_B1",
         "STEPNUM": 1, "RES": "RES2", "PRODDUR": 0.8},
    ])


def _inventory_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "QTY": 50.0, "ON_HAND": 50.0,
         "ON_ORDER": 0.0, "ALLOCATED": 0.0},
        {"ITEM": "ITEM_B", "LOC": "D2", "QTY": 30.0, "ON_HAND": 30.0,
         "ON_ORDER": 0.0, "ALLOCATED": 0.0},
    ])


def _schedrcpts_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "SCHED_DATE": "2026-10-01",
         "QTY": 100.0, "QUANTITY": 100.0},
    ])


def _customer_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"CUST": "CUST1", "DESCR": "Customer One"},
        {"CUST": "CUST2", "DESCR": "Customer Two"},
    ])


def _customerorder_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"CUST": "CUST1", "ORDERID": "ORD-001", "ITEM": "ITEM_A",
         "LOC": "D1", "QTY": 200.0},
        {"CUST": "CUST2", "ORDERID": "ORD-002", "ITEM": "ITEM_B",
         "LOC": "D2", "QTY": 100.0},
    ])


def _dfutoskufcst_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "SKULOC": "D1", "STARTDATE": "20261001000000",
         "TOTFCST": 600.0},
        {"ITEM": "ITEM_B", "SKULOC": "D2", "STARTDATE": "20261001000000",
         "TOTFCST": 200.0},
    ])


def _skueffinventoryparam_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "MAXOHQTY": 1000.0, "ENABLEOPT": 1},
        {"ITEM": "ITEM_B", "LOC": "D2", "MAXOHQTY": 800.0, "ENABLEOPT": 1},
    ])


def _supersession_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "ALTITEM": "ITEM_A_ALT",
         "ALTITEMPRIORITY": 1, "ENABLEOPT": 1},
    ])


def _altbillofmaterials_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "SUBORD": "COMP_X_ALT", "LOC": "D1",
         "ALTSUBORD": "COMP_X", "DRAWQTY": 2.0},
    ])


def _calendars_df() -> pd.DataFrame:
    return pd.DataFrame([{"CAL": "CAL1", "DESCR": "Standard Calendar"}])


def _calpattern_df() -> pd.DataFrame:
    return pd.DataFrame([{"CAL": "CAL1", "PATTERN": "PAT1"}])


def _calattribute_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"CAL": "CAL1", "ATTRIBUTE": "HOURS_PER_DAY", "VALUE": "24"},
    ])


def _purchmethod_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "PURCHMETHOD": "PM_P_A"},
    ])


ALL_ENTITY_BUILDERS = {
    "sourcing": _sourcing_df,
    "sku": _sku_df,
    "locations": _locations_df,
    "items": _items_df,
    "network": _network_df,
    "res": _res_df,
    "billofmaterials": _bom_df,
    "productionmethod": _productionmethod_df,
    "productionstep": _productionstep_df,
    "inventory": _inventory_df,
    "schedrcpts": _schedrcpts_df,
    "customer": _customer_df,
    "customerorder": _customerorder_df,
    "dfutoskufcst": _dfutoskufcst_df,
    "skueffinventoryparam": _skueffinventoryparam_df,
    "supersession": _supersession_df,
    "altbillofmaterials": _altbillofmaterials_df,
    "calendars": _calendars_df,
    "calpattern": _calpattern_df,
    "calattribute": _calattribute_df,
    "purchmethod": _purchmethod_df,
}


def _build_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep="|", lineterminator="\n").encode("utf-8")


def _build_all_upload_files() -> list[tuple[str, tuple[str, io.BytesIO, str]]]:
    """Return list of (field_name, (filename, BytesIO, content_type)) for upload."""
    files = []
    for entity, builder in ALL_ENTITY_BUILDERS.items():
        df = builder()
        csv_bytes = _build_csv_bytes(df)
        filename = _ts(entity)
        files.append(("files", (filename, io.BytesIO(csv_bytes), "text/csv")))
    return files


# ---------------------------------------------------------------------------
# Step 1: Upload 22 BY CSV files
# ---------------------------------------------------------------------------


class TestStep1UploadBatch:

    def test_upload_batch_returns_200_with_all_entities(self) -> None:
        """POST /upload/ with all 22 BY CSVs validates every entity."""
        files = _build_all_upload_files()
        resp = client.post("/upload/", files=files)

        assert resp.status_code == 200, (
            f"Upload failed: {resp.status_code} — {resp.text[:500]}"
        )
        body = resp.json()
        assert body["message"] == "Files uploaded and validated successfully"

        results = body["results"]
        assert "snop" in results, "Expected 'snop' key in results"
        snop = results["snop"]
        assert len(snop) == len(ALL_ENTITY_BUILDERS), (
            f"Expected {len(ALL_ENTITY_BUILDERS)} entities, got {len(snop)}"
        )
        for entity in ALL_ENTITY_BUILDERS:
            assert entity in snop, f"Entity '{entity}' missing from snop results"
            meta = snop[entity]
            assert meta["rows"] > 0, f"Entity '{entity}' has 0 rows"
            assert len(meta["columns"]) > 0, f"Entity '{entity}' has no columns"

    def test_upload_rejects_empty_batch(self) -> None:
        resp = client.post("/upload/", files=[])
        assert resp.status_code in (400, 422)

    def test_upload_rejects_unknown_filename(self) -> None:
        bad = io.BytesIO(b"COL1|COL2\nA|B\n")
        resp = client.post("/upload/", files=[("files", ("garbage.csv", bad, "text/csv"))])
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Step 2: Dual-solver simulation run
# ---------------------------------------------------------------------------


def _run_simulation(solver: str) -> dict:
    sourcing = _build_csv_bytes(_sourcing_df())
    sku = _build_csv_bytes(_sku_df())
    bom = _build_csv_bytes(_bom_df())
    res = _build_csv_bytes(_res_df())
    pm = _build_csv_bytes(_productionmethod_df())
    ps = _build_csv_bytes(_productionstep_df())
    inv = _build_csv_bytes(_inventory_df())
    sr = _build_csv_bytes(_schedrcpts_df())
    fcst = _build_csv_bytes(_dfutoskufcst_df())
    items = _build_csv_bytes(_items_df())
    sup = _build_csv_bytes(_supersession_df())

    resp = client.post(
        f"/run-simulation/?solver={solver}",
        files=[
            ("sourcing", ("sourcing.csv", io.BytesIO(sourcing), "text/csv")),
            ("sku", ("sku.csv", io.BytesIO(sku), "text/csv")),
            ("bom", ("bom.csv", io.BytesIO(bom), "text/csv")),
            ("res", ("res.csv", io.BytesIO(res), "text/csv")),
            ("productionmethod", ("pm.csv", io.BytesIO(pm), "text/csv")),
            ("productionstep", ("ps.csv", io.BytesIO(ps), "text/csv")),
            ("inventory", ("inv.csv", io.BytesIO(inv), "text/csv")),
            ("schedrcpts", ("sr.csv", io.BytesIO(sr), "text/csv")),
            ("dfutoskufcst", ("fcst.csv", io.BytesIO(fcst), "text/csv")),
            ("items", ("items.csv", io.BytesIO(items), "text/csv")),
            ("supersession", ("sup.csv", io.BytesIO(sup), "text/csv")),
        ],
        data={"risk_adjustments": "{}"},
    )
    return resp


def _assert_simulation_result(data: dict, solver_label: str) -> None:
    assert data["status"] in ("optimal", "feasible", "infeasible"), (
        f"{solver_label}: unexpected status {data['status']}"
    )
    summary = data.get("summary", {})
    assert "met_pct" in summary, f"{solver_label}: missing met_pct"
    assert "total_demand_qty" in summary, f"{solver_label}: missing total_demand_qty"

    fill_rate = summary["met_pct"]
    assert isinstance(fill_rate, (int, float)), f"{solver_label}: met_pct not numeric"
    assert 0 <= fill_rate <= 100, f"{solver_label}: fill rate {fill_rate} out of range"

    on_time = summary.get("late_pct")
    if on_time is not None:
        assert isinstance(on_time, (int, float)), f"{solver_label}: late_pct not numeric"

    landed_cost = data.get("total_cost")
    assert landed_cost is not None, f"{solver_label}: missing total_cost"
    assert isinstance(landed_cost, (int, float)), f"{solver_label}: total_cost not numeric"
    assert landed_cost >= 0, f"{solver_label}: negative cost {landed_cost}"


class TestStep2SimulationRun:

    def test_heuristic_solver_returns_valid_metrics(self) -> None:
        resp = _run_simulation("heuristic")
        assert resp.status_code == 200, f"Heuristic failed: {resp.text[:500]}"
        _assert_simulation_result(resp.json(), "heuristic")

    def test_lp_solver_returns_valid_metrics(self) -> None:
        resp = _run_simulation("lp")
        assert resp.status_code == 200, f"LP failed: {resp.text[:500]}"
        _assert_simulation_result(resp.json(), "lp")

    def test_compare_both_solvers_on_same_data(self) -> None:
        """Run both solvers independently and verify comparable results."""
        h_resp = _run_simulation("heuristic")
        lp_resp = _run_simulation("lp")

        assert h_resp.status_code == 200, f"Heuristic: {h_resp.text[:300]}"
        assert lp_resp.status_code == 200, f"LP: {lp_resp.text[:300]}"

        h_data = h_resp.json()
        lp_data = lp_resp.json()

        _assert_simulation_result(h_data, "heuristic")
        _assert_simulation_result(lp_data, "lp")

        h_summary = h_data["summary"]
        lp_summary = lp_data["summary"]

        # Both solvers see the same total demand
        assert h_summary["total_demand_qty"] == pytest.approx(
            lp_summary["total_demand_qty"], abs=0.01
        ), "Solvers disagree on total demand"

        # LP cost should be <= heuristic cost (LP is optimal)
        if h_data["status"] == "optimal" and lp_data["status"] == "optimal":
            assert lp_data["total_cost"] <= h_data["total_cost"] + 0.01, (
                f"LP cost {lp_data['total_cost']} > heuristic cost {h_data['total_cost']}"
            )

    def test_auto_solver_selects_best(self) -> None:
        resp = _run_simulation("auto")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("optimal", "feasible", "infeasible")


# ---------------------------------------------------------------------------
# Step 3: Network graph for React Flow
# ---------------------------------------------------------------------------


def _write_entity_csvs_to_dir(tmp_dir: Path) -> None:
    for entity, builder in ALL_ENTITY_BUILDERS.items():
        df = builder()
        (tmp_dir / _ts(entity)).write_bytes(_build_csv_bytes(df))


class TestStep3NetworkGraph:

    def test_network_graph_returns_node_link_payload(self, tmp_path: Path) -> None:
        _write_entity_csvs_to_dir(tmp_path)
        scenario_id = "e2e_test_scenario"

        resp = client.get(
            f"/api/v1/simulation/network-graph/{scenario_id}",
            params={"data_dir": str(tmp_path)},
        )
        assert resp.status_code == 200, f"Network graph failed: {resp.text[:500]}"
        body = resp.json()

        # Top-level keys
        assert "nodes" in body, "Missing 'nodes'"
        assert "edges" in body, "Missing 'edges'"
        assert "summary" in body, "Missing 'summary'"
        assert body["scenario_id"] == scenario_id

        nodes = body["nodes"]
        edges = body["edges"]
        summary = body["summary"]

        assert isinstance(nodes, list), "nodes is not a list"
        assert isinstance(edges, list), "edges is not a list"
        assert len(nodes) > 0, "No nodes returned"

        # Validate node structure for React Flow
        for node in nodes:
            assert "id" in node, f"Node missing 'id': {node}"
            assert "label" in node, f"Node missing 'label': {node}"
            assert "type" in node, f"Node missing 'type': {node}"
            assert node["type"] in ("plant", "dc", "supplier", "customer", "resource"), (
                f"Unknown node type: {node['type']}"
            )
            metrics = node.get("metrics", {})
            util_pct = metrics.get("utilization_pct")
            assert util_pct is not None, f"Node {node['id']} missing utilization_pct"
            assert isinstance(util_pct, (int, float)), (
                f"Node {node['id']} utilization_pct not numeric"
            )
            assert 0 <= util_pct <= 100 or util_pct == 0, (
                f"Node {node['id']} utilization_pct {util_pct} out of range"
            )

        # Validate edge structure
        for edge in edges:
            assert "id" in edge, f"Edge missing 'id': {edge}"
            assert "source" in edge, f"Edge missing 'source': {edge}"
            assert "target" in edge, f"Edge missing 'target': {edge}"
            vol = edge.get("baseline_volume", edge.get("simulated_volume", 0))
            assert isinstance(vol, (int, float)), (
                f"Edge {edge['id']} volume not numeric"
            )
            assert "is_congested" in edge, f"Edge {edge['id']} missing is_congested"
            assert isinstance(edge["is_congested"], bool), (
                f"Edge {edge['id']} is_congested not bool"
            )

        # Summary assertions
        assert summary["total_nodes"] == len(nodes)
        assert summary["total_edges"] == len(edges)
        assert "nodes_by_type" in summary
        assert "congested_edges" in summary

    def test_network_graph_empty_data_dir_returns_error(self) -> None:
        resp = client.get(
            "/api/v1/simulation/network-graph/empty_test",
            params={"data_dir": "/nonexistent/path"},
        )
        assert resp.status_code in (404, 500)


# ---------------------------------------------------------------------------
# Step 4: Commit-to-BY — export patched .zip
# ---------------------------------------------------------------------------


class TestStep4CommitToBy:

    def test_export_by_patch_produces_nonempty_zip(self) -> None:
        sourcing_df = _sourcing_df()
        sku_df = _sku_df()

        sourcing_bytes = _build_csv_bytes(sourcing_df)
        sku_bytes = _build_csv_bytes(sku_df)

        deltas = json.dumps([
            {
                "entity": "sourcing",
                "key": "ITEM_A|SRC1|D1",
                "updates": {"FACTOR": 0.75},
            }
        ])
        impact = json.dumps({"mitigation_cost": 5000, "protected_revenue": 25000})

        resp = client.post(
            "/api/v1/simulation/export-by-patch",
            files=[
                ("files", (_ts("sourcing"), io.BytesIO(sourcing_bytes), "text/csv")),
                ("files", (_ts("sku"), io.BytesIO(sku_bytes), "text/csv")),
            ],
            data={
                "scenario_deltas": deltas,
                "scenario_id": "e2e_commit_test",
                "justification": "E2E test mitigation",
                "financial_impact": impact,
            },
        )
        assert resp.status_code == 200, f"Export failed: {resp.text[:500]}"
        assert resp.headers["content-type"] == "application/zip"

        archive_bytes = resp.content
        assert len(archive_bytes) > 0, "Empty archive"

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            names = zf.namelist()
            assert len(names) > 0, "ZIP has no entries"

            # Must contain patched CSV files
            csv_files = [n for n in names if n.endswith(".csv")]
            assert len(csv_files) >= 1, f"No CSV files in archive: {names}"

            # Must contain change manifest
            assert "change_manifest.json" in names, f"Missing manifest: {names}"
            manifest = json.loads(zf.read("change_manifest.json"))
            assert manifest["scenario_id"] == "e2e_commit_test"
            assert manifest["change_count"] >= 1

            # Must contain UI instructions
            assert "BY_UI_Instructions.txt" in names, f"Missing instructions: {names}"
            instructions = zf.read("BY_UI_Instructions.txt").decode("utf-8")
            assert "e2e_commit_test" in instructions

            # Verify patched sourcing CSV has the updated FACTOR
            sourcing_csv = [n for n in csv_files if "sourcing" in n]
            assert sourcing_csv, "No sourcing CSV in archive"
            patched_df = pd.read_csv(
                io.StringIO(zf.read(sourcing_csv[0]).decode("utf-8")), sep="|"
            )
            patched_df.columns = [c.strip().upper() for c in patched_df.columns]
            mask = (
                (patched_df["ITEM"] == "ITEM_A")
                & (patched_df["SOURCE"] == "SRC1")
                & (patched_df["DEST"] == "D1")
            )
            assert mask.any(), "Patched row not found"
            assert patched_df.loc[mask, "FACTOR"].iloc[0] == 0.75

    def test_export_by_patch_no_deltas_returns_full_archive(self) -> None:
        sourcing_bytes = _build_csv_bytes(_sourcing_df())
        sku_bytes = _build_csv_bytes(_sku_df())

        resp = client.post(
            "/api/v1/simulation/export-by-patch",
            files=[
                ("files", (_ts("sourcing"), io.BytesIO(sourcing_bytes), "text/csv")),
                ("files", (_ts("sku"), io.BytesIO(sku_bytes), "text/csv")),
            ],
            data={"scenario_deltas": "[]", "scenario_id": "no_change"},
        )
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            manifest = json.loads(zf.read("change_manifest.json"))
            assert manifest["change_count"] == 0

    def test_export_by_patch_rejects_empty_files(self) -> None:
        resp = client.post(
            "/api/v1/simulation/export-by-patch",
            files=[],
            data={"scenario_deltas": "[]"},
        )
        assert resp.status_code in (400, 422)

    def test_export_by_patch_rejects_invalid_json(self) -> None:
        sourcing_bytes = _build_csv_bytes(_sourcing_df())
        resp = client.post(
            "/api/v1/simulation/export-by-patch",
            files=[("files", (_ts("sourcing"), io.BytesIO(sourcing_bytes), "text/csv"))],
            data={"scenario_deltas": "not-json"},
        )
        assert resp.status_code == 400
