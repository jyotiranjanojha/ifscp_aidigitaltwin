from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.optimization.demand_engine import run_demand_pegging_optimization  # noqa: E402


def test_demand_engine_splits_met_late_and_unmet() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE dfutoskufcst (ITEM VARCHAR, SKULOC VARCHAR, DMDGROUP VARCHAR, STARTDATE VARCHAR, TOTFCST DOUBLE)")
    conn.execute("INSERT INTO dfutoskufcst VALUES ('A', 'D', 'C1', '2025-01-01', 8), ('B', 'D', 'C1', '2025-01-01', 2)")
    conn.execute("CREATE TABLE customerorder (ORDERID VARCHAR, CUST VARCHAR, ITEM VARCHAR, LOC VARCHAR, QTY DOUBLE, DELRDD_CALC_DT VARCHAR, PRIORITY INTEGER)")
    conn.execute("CREATE TABLE sourcing (ITEM VARCHAR, SOURCE VARCHAR, DEST VARCHAR, PRIORITY DOUBLE, FACTOR DOUBLE)")
    conn.execute("INSERT INTO sourcing VALUES ('A', 'S', 'D', 1, 0.000005), ('B', 'S', 'D', 1, 0)")
    conn.execute("CREATE TABLE inventory (ITEM VARCHAR, LOC VARCHAR, QTY DOUBLE)")
    conn.execute("CREATE TABLE schedrcpts (ITEM VARCHAR, LOC VARCHAR, SCHED_DATE VARCHAR, QTY DOUBLE)")
    conn.execute("CREATE TABLE productionmethod (ITEM VARCHAR, LOC VARCHAR, PRODUCTIONMETHOD VARCHAR)")
    conn.execute("CREATE TABLE productionstep (ITEM VARCHAR, LOC VARCHAR, PRODUCTIONMETHOD VARCHAR, RES VARCHAR, PRODDUR DOUBLE)")
    conn.execute("CREATE TABLE billofmaterials (ITEM VARCHAR, SUBORD VARCHAR, LOC VARCHAR, DRAWQTY DOUBLE)")
    conn.execute("CREATE TABLE res (RES VARCHAR, LOC VARCHAR)")

    result = run_demand_pegging_optimization(conn, max_late_periods=1)
    statuses = [record["status"] for record in result["pegging_records"]]

    assert result["status"] == "optimal"
    assert result["summary"]["total_demand_qty"] == 10.0
    assert result["summary"]["met_qty"] == 5.0
    assert result["summary"]["late_qty"] == 3.0
    assert result["summary"]["unmet_qty"] == 2.0
    assert result["summary"]["avg_delay_days"] == 1.0
    assert set(statuses) == {"MET", "LATE_MET", "UNMET"}