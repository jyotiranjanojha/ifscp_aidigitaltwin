from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.optimization.demand_engine import DemandPeggingEngine  # noqa: E402
from app.services.bottleneck_tracer import SOURCING_CONSTRAINED, trace_bottlenecks  # noqa: E402


def test_trace_bottlenecks_returns_json_summary_for_unmet_and_late_demand() -> None:
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

    engine = DemandPeggingEngine(conn, max_late_periods=1)
    engine.data = engine._build_data()
    model = engine._build_model(engine.data)
    engine_result = engine.run()
    diagnostics = engine_result["diagnostics"] or trace_bottlenecks(model, engine.data)

    assert diagnostics
    assert all({"order_id", "item", "customer", "unmet_qty", "root_cause", "bottleneck_entity", "suggested_mitigation"}.issubset(row) for row in diagnostics)
    assert any(row["root_cause"] == SOURCING_CONSTRAINED for row in diagnostics)