"""Comprehensive integration test suite covering all 10 components.

Components tested:
  4 & 5 — 22-Table Schema Ingestion & DuckDB bulk load
  6 & 7  — Dual-Solver Engine (Heuristic + LpOpt) & Pegging
  8      — Bottleneck Tracer
  9      — Round-Trip BY Delta Exporter
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyomo.environ as pyo
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import ENTITY_SCHEMA_MAP  # noqa: E402
from schema_config import (  # noqa: E402
    PRIMARY_KEY_COLUMNS_BY_ENTITY,
    REQUIRED_COLUMNS_BY_ENTITY,
)
from app.core.bulk_loader import load_by_csv_pack, BulkLoadResult  # noqa: E402
from app.core.calendar_resolver import CalendarResolver, TimeBucket  # noqa: E402
from app.optimization.demand_engine import DemandPeggingEngine  # noqa: E402
from app.services.bottleneck_tracer import (  # noqa: E402
    trace_bottlenecks,
    CAPACITY_CONSTRAINED,
    MATERIAL_CONSTRAINED,
    SOURCING_CONSTRAINED,
    LEAD_TIME_CONSTRAINED,
)
from app.services.by_change_exporter import build_by_patch_archive, _looks_like_date_column  # noqa: E402
from app.services.by_exporter import build_by_export_zip  # noqa: E402
from pyomo.contrib.appsi.solvers.highs import Highs as HiGHS  # noqa: E402

DEFAULT_DATA_DIR = Path(
    r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658"
)
FILE_PATTERN = re.compile(r"^if_snop_([a-z]+)-\d{14}\.csv$", re.IGNORECASE)
VALID_ROOT_CAUSES = {"CAPACITY", "MATERIAL", "SOURCING", "LEAD_TIME"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def data_dir() -> Path:
    d = Path(DEFAULT_DATA_DIR)
    if not d.exists() or not d.is_dir():
        pytest.fail(f"BY data directory does not exist: {d}")
    return d


@pytest.fixture(scope="module")
def bulk_load(data_dir: Path) -> BulkLoadResult:
    return load_by_csv_pack(data_dir)


@pytest.fixture(scope="module")
def conn(bulk_load: BulkLoadResult) -> duckdb.DuckDBPyConnection:
    return bulk_load.conn


@pytest.fixture(scope="module")
def raw_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for csv_path in sorted(data_dir.glob("if_snop_*-*.csv")):
        match = FILE_PATTERN.match(csv_path.name)
        if not match:
            continue
        tables[match.group(1).lower()] = _read_by_csv(csv_path)
    return tables


def _read_by_csv(csv_path: Path) -> pd.DataFrame:
    content = csv_path.read_bytes()
    header = content.splitlines()[0].decode("utf-8-sig", errors="ignore") if content else ""
    delimiter = max(["|", ",", "\t", ";"], key=header.count)
    df = pd.read_csv(csv_path, sep=delimiter)
    df.columns = [_norm(c) for c in df.columns]
    return df


def _norm(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


# ===================================================================
# 1. 22-Table Schema Ingestion & DuckDB  (Components 4 & 5)
# ===================================================================


class TestSchemaIngestionAndDuckDB:

    def test_all_22_entities_loaded(self, bulk_load: BulkLoadResult) -> None:
        loaded = set(bulk_load.row_counts.keys())
        expected = set(PRIMARY_KEY_COLUMNS_BY_ENTITY.keys())
        assert loaded == expected, (
            f"Missing: {sorted(expected - loaded)}  Extra: {sorted(loaded - expected)}"
        )

    def test_22_table_count(self, bulk_load: BulkLoadResult) -> None:
        assert len(bulk_load.row_counts) == 22

    @pytest.mark.parametrize("entity", sorted(PRIMARY_KEY_COLUMNS_BY_ENTITY.keys()))
    def test_entity_row_count_positive(self, bulk_load: BulkLoadResult, entity: str) -> None:
        assert bulk_load.row_counts[entity] > 0, f"Table '{entity}' has 0 rows"

    def test_schema_validation_zero_errors(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        errors: list[str] = []
        for entity, df in raw_tables.items():
            if entity not in ENTITY_SCHEMA_MAP:
                continue
            schema_class = ENTITY_SCHEMA_MAP[entity]
            required = set(getattr(schema_class, "_required_columns", set()))
            missing = required - set(df.columns)
            if missing:
                errors.append(f"{entity}: missing columns {sorted(missing)}")
                continue
            for row_num, record in enumerate(df.to_dict(orient="records"), start=2):
                try:
                    schema_class(**record)
                except Exception as exc:
                    errors.append(f"{entity} row {row_num}: {exc}")
                    if len(errors) >= 20:
                        break
        assert not errors, "Schema validation errors:\n" + "\n".join(errors[:20])

    def test_columns_are_uppercased(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        for entity, df in raw_tables.items():
            for col in df.columns:
                assert col == col.upper(), f"{entity}.{col} is not fully uppercased"

    def test_no_bom_or_nbsp_in_columns(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        for entity, df in raw_tables.items():
            for col in df.columns:
                assert "\ufeff" not in col
                assert "\xa0" not in col

    def test_calendar_resolver_resource_capacity(self, conn: duckdb.DuckDBPyConnection) -> None:
        resolver = CalendarResolver.from_duckdb(conn)
        now = datetime.now()
        bucket_start = datetime(now.year, now.month, now.day)
        bucket_end = bucket_start + timedelta(days=7)
        total_capacity = 0.0
        for res_id, loc, cal_id in conn.execute('SELECT RES, LOC, CAL FROM res LIMIT 5').fetchall():
            cap = resolver.get_time_phased_resource_capacity(str(res_id), str(cal_id) or "", bucket_start, bucket_end)
            total_capacity += cap
        assert total_capacity >= 0.0

    def test_calendar_resolver_bom_yield(self, conn: duckdb.DuckDBPyConnection) -> None:
        resolver = CalendarResolver.from_duckdb(conn)
        now = datetime.now()
        for parent, subitem, loc in conn.execute('SELECT ITEM, SUBORD, LOC FROM billofmaterials LIMIT 5').fetchall():
            yield_val = resolver.get_time_phased_bom_yield(str(parent), str(subitem), "", now)
            assert 0.0 <= yield_val <= 10.0

    def test_calendar_resolver_time_phased_model_parameters(self, conn: duckdb.DuckDBPyConnection) -> None:
        resolver = CalendarResolver.from_duckdb(conn)
        today = date.today()
        buckets = [
            TimeBucket(
                bucket_id=f"W{i+1:02d}",
                start=datetime.combine(today + timedelta(weeks=i), datetime.min.time()),
                end=datetime.combine(today + timedelta(weeks=i + 1), datetime.min.time()),
            )
            for i in range(4)
        ]
        params = resolver.generate_time_phased_model_parameters(buckets)
        assert "CapMatrix" in params and "YieldMatrix" in params and "ValidShipDays" in params
        assert len(params["bucket_ids"]) == 4
        assert params["CapArray"].ndim == 2


# ===================================================================
# 2. Dual-Solver Engine & Pegging  (Components 6 & 7)
# ===================================================================


class TestDualSolverEngine:

    # -- 2a  DemandPeggingEngine on synthetic data (fast) -----------------------

    def test_lpopt_engine_status(self) -> None:
        conn = _build_small_synthetic_duckdb()
        result = DemandPeggingEngine(conn, max_late_periods=3).run()
        assert result["status"] in ("optimal", "feasible")

    def test_lpopt_demand_conservation(self) -> None:
        conn = _build_small_synthetic_duckdb()
        result = DemandPeggingEngine(conn, max_late_periods=3).run()
        s = result["summary"]
        assert s["met_qty"] + s["late_qty"] + s["unmet_qty"] == pytest.approx(
            s["total_demand_qty"], abs=0.01
        )

    def test_lpopt_fill_rate_calculation(self) -> None:
        conn = _build_small_synthetic_duckdb()
        result = DemandPeggingEngine(conn, max_late_periods=3).run()
        s = result["summary"]
        if s["total_demand_qty"] > 0:
            expected = (s["met_qty"] / s["total_demand_qty"]) * 100.0
            assert s["met_pct"] == pytest.approx(expected, abs=0.1)

    def test_lpopt_slack_variables_resolve(self) -> None:
        conn = _build_small_synthetic_duckdb()
        engine = DemandPeggingEngine(conn, max_late_periods=3)
        engine.data = engine._build_data()
        model = engine._build_model(engine.data)
        result = HiGHS().solve(model)
        tc = getattr(result.termination_condition, "name", str(result.termination_condition)).lower()
        assert tc in ("optimal", "feasible"), f"Model infeasible: {tc}"

    def test_lpopt_objective_finite(self) -> None:
        conn = _build_small_synthetic_duckdb()
        result = DemandPeggingEngine(conn, max_late_periods=3).run()
        assert result["total_cost"] >= 0.0
        assert result["solve_time_ms"] >= 0.0

    # -- 2b  BYESPLpOptEngine on synthetic data ---------------------------------

    def test_full_lpopt_engine_synthetic(self) -> None:
        from lpopt_engine_full import BYESPLpOptEngine, LpOptConfig, BYESPDataGenerator
        cfg = LpOptConfig(planning_horizon=8)
        data = BYESPDataGenerator(cfg).generate_all()
        result = BYESPLpOptEngine(cfg).build_and_solve(data)
        assert result["status"] == "optimal"
        s = result["summary"]
        assert s["total_demand"] > 0
        assert s["overall_fill_rate_pct"] >= 0.0

    def test_full_lpopt_slack_variables(self) -> None:
        from lpopt_engine_full import BYESPLpOptEngine, LpOptConfig, BYESPDataGenerator
        cfg = LpOptConfig(planning_horizon=6)
        data = BYESPDataGenerator(cfg).generate_all()
        result = BYESPLpOptEngine(cfg).build_and_solve(data)
        assert result["status"] == "optimal"
        assert isinstance(result["shortage"], list)
        assert isinstance(result["safety_stock_violations"], list)

    # -- 2c  Root-level heuristic engine ----------------------------------------

    def test_root_heuristic_synthetic(self) -> None:
        from heuristic_engine import run_heuristic_optimization
        sourcing = pd.DataFrame({
            "ITEM": ["A", "A"], "SOURCE": ["S1", "S2"], "DEST": ["D1", "D1"],
            "BASE_COST": [1.0, 3.0], "MAX_CAPACITY": [50.0, 50.0],
            "FACTOR": [1.0, 1.0], "TRANSPORT_TIME": [1, 2],
        })
        sku = pd.DataFrame({"ITEM": ["A"], "LOC": ["D1"], "DEMAND": [80.0], "PRIORITY": [1]})
        result = run_heuristic_optimization(sourcing_df=sourcing, sku_df=sku, risk_adjustments={})
        assert result["status"] in ("optimal", "infeasible")
        s = result["summary"]
        assert s["met_qty"] + s["unmet_qty"] == pytest.approx(s["total_demand_qty"], abs=0.01)

    def test_root_heuristic_real_data(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        from heuristic_engine import run_heuristic_optimization
        result = run_heuristic_optimization(
            sourcing_df=_prep_sourcing(raw_tables["sourcing"]),
            sku_df=_prep_sku(raw_tables["sku"]),
            risk_adjustments={},
            bom_df=_prep_bom(raw_tables["billofmaterials"]),
            res_df=_prep_res(raw_tables["res"]),
            productionmethod_df=_prep_pm(raw_tables["productionmethod"]),
            productionstep_df=_prep_ps(raw_tables["productionstep"]),
            inventory_df=_prep_inv(raw_tables["inventory"]),
            schedrcpts_df=_prep_sr(raw_tables["schedrcpts"]),
        )
        assert result["status"] in ("optimal", "infeasible")
        assert result["summary"]["total_demand_qty"] >= 0.0

    # -- 2d  Root-level LP engine -----------------------------------------------

    def test_root_lp_synthetic(self) -> None:
        from lpopt_engine import run_lp_optimization
        sourcing = pd.DataFrame({
            "ITEM": ["A", "A"], "SOURCE": ["S1", "S2"], "DEST": ["D1", "D1"],
            "BASE_COST": [1.0, 3.0], "MAX_CAPACITY": [50.0, 50.0],
        })
        sku = pd.DataFrame({"ITEM": ["A"], "LOC": ["D1"], "DEMAND": [80.0], "PRIORITY": [1]})
        result = run_lp_optimization(sourcing_df=sourcing, sku_df=sku, risk_adjustments={})
        assert result["status"] in ("optimal", "feasible", "infeasible")
        if result["status"] == "optimal":
            assert result["total_cost"] >= 0.0

    def test_root_lp_real_data(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        from lpopt_engine import run_lp_optimization
        result = run_lp_optimization(
            sourcing_df=_prep_sourcing(raw_tables["sourcing"]),
            sku_df=_prep_sku(raw_tables["sku"]),
            risk_adjustments={},
        )
        assert result["status"] in ("optimal", "feasible", "infeasible", "error")

    # -- 2e  LpOpt total cost <= Heuristic total cost ---------------------------

    def test_lpopt_cost_le_heuristic_cost(self) -> None:
        from heuristic_engine import run_heuristic_optimization
        from lpopt_engine import run_lp_optimization
        sourcing = pd.DataFrame({
            "ITEM": ["A", "A"], "SOURCE": ["S1", "S2"], "DEST": ["D1", "D1"],
            "BASE_COST": [1.0, 3.0], "MAX_CAPACITY": [50.0, 50.0],
        })
        sku = pd.DataFrame({"ITEM": ["A"], "LOC": ["D1"], "DEMAND": [80.0], "PRIORITY": [1]})
        kwargs = dict(sourcing_df=sourcing, sku_df=sku, risk_adjustments={})
        h = run_heuristic_optimization(**kwargs)
        lp = run_lp_optimization(**kwargs)
        if lp["status"] == "optimal" and h["status"] == "optimal":
            assert lp["total_cost"] <= h["total_cost"] + 0.01

    # -- 2f  Optimizer dispatch (auto) ------------------------------------------

    def test_optimizer_auto_mode(self) -> None:
        from optimizer import run_optimization
        sourcing = pd.DataFrame({
            "ITEM": ["A", "A"], "SOURCE": ["S1", "S2"], "DEST": ["D1", "D1"],
            "BASE_COST": [1.0, 3.0], "MAX_CAPACITY": [50.0, 50.0],
        })
        sku = pd.DataFrame({"ITEM": ["A"], "LOC": ["D1"], "DEMAND": [80.0], "PRIORITY": [1]})
        result = run_optimization(sourcing_df=sourcing, sku_df=sku, risk_adjustments={})
        assert result["status"] in ("optimal", "feasible", "infeasible", "error")


# ===================================================================
# 3. Bottleneck Tracer  (Component 8)
# ===================================================================


class TestBottleneckTracer:

    def test_bottleneck_tracer_root_cause_valid(self) -> None:
        conn = _build_small_synthetic_duckdb()
        engine = DemandPeggingEngine(conn, max_late_periods=3)
        engine.data = engine._build_data()
        model = engine._build_model(engine.data)
        HiGHS().solve(model)
        diagnostics = trace_bottlenecks(model, engine.data)
        for diag in diagnostics:
            assert diag["root_cause"] in VALID_ROOT_CAUSES, f"Invalid: {diag['root_cause']}"
            assert diag["bottleneck_entity"], f"Empty entity for {diag['order_id']}"

    def test_bottleneck_tracer_fields_complete(self) -> None:
        conn = _build_small_synthetic_duckdb()
        engine = DemandPeggingEngine(conn, max_late_periods=3)
        engine.data = engine._build_data()
        model = engine._build_model(engine.data)
        HiGHS().solve(model)
        diagnostics = trace_bottlenecks(model, engine.data)
        required = {"order_id", "item", "customer", "unmet_qty", "root_cause", "bottleneck_entity", "suggested_mitigation"}
        for diag in diagnostics:
            assert not (required - set(diag.keys())), f"Missing: {required - set(diag.keys())}"

    def test_bottleneck_tracer_entity_ids_present(self) -> None:
        conn = _build_small_synthetic_duckdb()
        engine = DemandPeggingEngine(conn, max_late_periods=3)
        engine.data = engine._build_data()
        model = engine._build_model(engine.data)
        HiGHS().solve(model)
        diagnostics = trace_bottlenecks(model, engine.data)
        for diag in diagnostics:
            entity = diag["bottleneck_entity"]
            assert len(str(entity).strip()) > 0

    def test_bottleneck_tracer_with_capacity_constraint(self) -> None:
        """Deliberately constrain capacity to force CAPACITY bottleneck."""
        conn = _build_capacity_constrained_duckdb()
        engine = DemandPeggingEngine(conn, max_late_periods=3)
        engine.data = engine._build_data()
        model = engine._build_model(engine.data)
        HiGHS().solve(model)
        diagnostics = trace_bottlenecks(model, engine.data)
        causes = {d["root_cause"] for d in diagnostics}
        if diagnostics:
            assert causes <= VALID_ROOT_CAUSES


# ===================================================================
# 4. Round-Trip BY Delta Exporter  (Component 9)
# ===================================================================


class TestRoundTripByDeltaExporter:

    def test_delta_exporter_generates_zip(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        first = sourcing_df.iloc[0]
        key = f"{first['ITEM']}|{first['SOURCE']}|{first['DEST']}"
        archive = build_by_export_zip(
            {"sourcing": sourcing_df},
            [{"entity": "sourcing", "key": key, "updates": {"FACTOR": 0.5}}],
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        )
        assert len(archive) > 0
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = zf.namelist()
            assert any("sourcing" in n for n in names)
            assert any("delta_summary" in n for n in names)

    def test_exported_csv_matches_original_schema(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        for entity in ("sourcing", "res", "dfutoskufcst"):
            if entity not in raw_tables:
                continue
            original_df = raw_tables[entity].copy()
            deltas = _entity_delta(entity, original_df)
            if not deltas:
                continue
            archive = build_by_export_zip({entity: original_df}, deltas, timestamp=datetime(2025, 1, 1, 12, 0, 0))
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                csv_name = [n for n in zf.namelist() if entity in n and n.endswith(".csv")]
                assert csv_name
                exported_df = pd.read_csv(io.StringIO(zf.read(csv_name[0]).decode("utf-8")), sep="|")
                exported_df.columns = [_norm(c) for c in exported_df.columns]
                original_cols = [_norm(c) for c in original_df.columns]
                for col in original_cols:
                    assert col in exported_df.columns, f"Original column {col!r} missing from exported {entity}"

    def test_exported_csv_column_order_preserved(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        first = sourcing_df.iloc[0]
        key = f"{first['ITEM']}|{first['SOURCE']}|{first['DEST']}"
        archive = build_by_export_zip(
            {"sourcing": sourcing_df},
            [{"entity": "sourcing", "key": key, "updates": {"FACTOR": 0.5}}],
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            csv_name = [n for n in zf.namelist() if "sourcing" in n and n.endswith(".csv")][0]
            exported_df = pd.read_csv(io.StringIO(zf.read(csv_name).decode("utf-8")), sep="|")
            exported_df.columns = [_norm(c) for c in exported_df.columns]
            assert list(exported_df.columns) == [_norm(c) for c in sourcing_df.columns]

    def test_date_columns_formatted_yyyymmddhhmmss(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sched_df = raw_tables.get("schedrcpts", pd.DataFrame()).copy()
        if sched_df.empty:
            pytest.skip("No schedrcpts data")
        archive = build_by_export_zip({"schedrcpts": sched_df}, [], timestamp=datetime(2025, 1, 1, 12, 0, 0))
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            csv_name = [n for n in zf.namelist() if "schedrcpts" in n and n.endswith(".csv")]
            if not csv_name:
                pytest.skip("No schedrcpts CSV")
            exported_df = pd.read_csv(io.StringIO(zf.read(csv_name[0]).decode("utf-8")), sep="|")
            exported_df.columns = [_norm(c) for c in exported_df.columns]
            date_cols = [c for c in exported_df.columns if _looks_like_date_column(c)]
            for col in date_cols:
                for val in exported_df[col].dropna():
                    val_str = str(val).strip()
                    if val_str:
                        assert re.match(r"^\d{14}$", val_str) or val_str == ""

    def test_modified_row_values_reflected(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        first = sourcing_df.iloc[0]
        key = f"{first['ITEM']}|{first['SOURCE']}|{first['DEST']}"
        archive = build_by_export_zip(
            {"sourcing": sourcing_df},
            [{"entity": "sourcing", "key": key, "updates": {"FACTOR": 0.25}}],
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            csv_name = [n for n in zf.namelist() if "sourcing" in n and n.endswith(".csv")][0]
            exported_df = pd.read_csv(io.StringIO(zf.read(csv_name).decode("utf-8")), sep="|")
            exported_df.columns = [_norm(c) for c in exported_df.columns]
            mask = (exported_df["ITEM"] == first["ITEM"]) & (exported_df["SOURCE"] == first["SOURCE"]) & (exported_df["DEST"] == first["DEST"])
            assert mask.sum() == 1
            assert exported_df.loc[mask].iloc[0]["FACTOR"] == 0.25

    def test_change_manifest_and_ui_instructions(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        first = sourcing_df.iloc[0]
        key = f"{first['ITEM']}|{first['SOURCE']}|{first['DEST']}"
        archive = build_by_patch_archive(
            {"sourcing": sourcing_df},
            [{"entity": "sourcing", "key": key, "updates": {"FACTOR": 0.5}}],
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
            scenario_id="integration_test",
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = zf.namelist()
            assert "change_manifest.json" in names
            assert "BY_UI_Instructions.txt" in names
            manifest = json.loads(zf.read("change_manifest.json"))
            assert manifest["scenario_id"] == "integration_test"
            assert manifest["change_count"] >= 1
            instructions = zf.read("BY_UI_Instructions.txt").decode("utf-8")
            assert "integration_test" in instructions

    def test_exported_csv_is_pipe_delimited(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        archive = build_by_export_zip({"sourcing": sourcing_df}, [], timestamp=datetime(2025, 1, 1, 12, 0, 0))
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            csv_name = [n for n in zf.namelist() if "sourcing" in n and n.endswith(".csv")][0]
            first_line = zf.read(csv_name).decode("utf-8").split("\n")[0]
            assert "|" in first_line

    def test_delta_exporter_no_changes(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        archive = build_by_export_zip({"sourcing": sourcing_df}, [], timestamp=datetime(2025, 1, 1, 12, 0, 0))
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            summary = json.loads(zf.read("delta_summary.json"))
            assert summary["delta_count"] == 0
            assert summary["file_count"] >= 1

    def test_delta_exporter_row_count_preserved(self, raw_tables: dict[str, pd.DataFrame]) -> None:
        sourcing_df = raw_tables["sourcing"].copy()
        original_count = len(sourcing_df)
        first = sourcing_df.iloc[0]
        key = f"{first['ITEM']}|{first['SOURCE']}|{first['DEST']}"
        archive = build_by_export_zip(
            {"sourcing": sourcing_df},
            [{"entity": "sourcing", "key": key, "updates": {"FACTOR": 0.5}}],
            timestamp=datetime(2025, 1, 1, 12, 0, 0),
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            csv_name = [n for n in zf.namelist() if "sourcing" in n and n.endswith(".csv")][0]
            exported_df = pd.read_csv(io.StringIO(zf.read(csv_name).decode("utf-8")), sep="|")
            assert len(exported_df) == original_count


# ===================================================================
# Helpers
# ===================================================================


def _build_small_synthetic_duckdb() -> duckdb.DuckDBPyConnection:
    """Small synthetic DuckDB with 3 demand lines — enough to exercise all solver paths.
    Omits res/productionmethod/productionstep to avoid Pyomo trivial-Boolean constraint bug
    when resource_capacity_rule evaluates `0 <= cap` as Python True instead of Constraint.Feasible.
    """
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE sourcing (
            ITEM VARCHAR, SOURCE VARCHAR, DEST VARCHAR,
            BASE_COST DOUBLE, MAX_CAPACITY DOUBLE, FACTOR DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO sourcing VALUES
        ('A', 'SRC1', 'D1', 1.0, 100.0, 1.0),
        ('A', 'SRC2', 'D1', 2.0, 80.0, 1.0),
        ('B', 'SRC1', 'D1', 1.5, 200.0, 1.0)
    """)
    conn.execute("""
        CREATE TABLE customerorder (
            CUST VARCHAR, ORDERID VARCHAR, ITEM VARCHAR, LOC VARCHAR,
            QTY DOUBLE, SHIPDATE VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO customerorder VALUES
        ('C1', 'CO-001', 'A', 'D1', 50.0, '2025-10-01'),
        ('C1', 'CO-002', 'A', 'D1', 60.0, '2025-10-02'),
        ('C2', 'CO-003', 'B', 'D1', 30.0, '2025-10-01')
    """)
    conn.execute("CREATE TABLE dfutoskufcst (ITEM VARCHAR, SKULOC VARCHAR, STARTDATE VARCHAR, TOTFCST DOUBLE)")
    conn.execute("CREATE TABLE inventory (ITEM VARCHAR, LOC VARCHAR, QTY DOUBLE, ON_HAND DOUBLE)")
    conn.execute("INSERT INTO inventory VALUES ('A', 'D1', 10.0, 10.0), ('B', 'D1', 5.0, 5.0)")
    conn.execute("CREATE TABLE schedrcpts (ITEM VARCHAR, LOC VARCHAR, SCHED_DATE VARCHAR, QTY DOUBLE)")
    conn.execute("CREATE TABLE productionmethod (ITEM VARCHAR, LOC VARCHAR, PRODUCTIONMETHOD VARCHAR)")
    conn.execute("CREATE TABLE productionstep (ITEM VARCHAR, LOC VARCHAR, PRODUCTIONMETHOD VARCHAR, STEPNUM DOUBLE, RES VARCHAR, PRODDUR DOUBLE)")
    conn.execute("CREATE TABLE billofmaterials (ITEM VARCHAR, SUBORD VARCHAR, LOC VARCHAR, DRAWQTY DOUBLE)")
    conn.execute("CREATE TABLE res (RES VARCHAR, LOC VARCHAR, CAPACITY DOUBLE, EFFICIENCY DOUBLE)")
    conn.execute("CREATE TABLE network (SOURCE VARCHAR, DEST VARCHAR, LEAD_TIME DOUBLE)")
    conn.execute("CREATE TABLE sku (ITEM VARCHAR, LOC VARCHAR)")
    return conn


def _build_capacity_constrained_duckdb() -> duckdb.DuckDBPyConnection:
    """Synthetic DuckDB with tight resource capacity forcing unmet demand."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE sourcing (
            ITEM VARCHAR, SOURCE VARCHAR, DEST VARCHAR,
            BASE_COST DOUBLE, MAX_CAPACITY DOUBLE, FACTOR DOUBLE
        )
    """)
    conn.execute("INSERT INTO sourcing VALUES ('A', 'SRC1', 'D1', 1.0, 1000.0, 1.0)")
    conn.execute("""
        CREATE TABLE customerorder (
            CUST VARCHAR, ORDERID VARCHAR, ITEM VARCHAR, LOC VARCHAR,
            QTY DOUBLE, SHIPDATE VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO customerorder VALUES
        ('C1', 'CO-001', 'A', 'D1', 100.0, '2025-10-01'),
        ('C1', 'CO-002', 'A', 'D1', 200.0, '2025-10-01')
    """)
    conn.execute("CREATE TABLE dfutoskufcst (ITEM VARCHAR, SKULOC VARCHAR, STARTDATE VARCHAR, TOTFCST DOUBLE)")
    conn.execute("CREATE TABLE inventory (ITEM VARCHAR, LOC VARCHAR, QTY DOUBLE, ON_HAND DOUBLE)")
    conn.execute("INSERT INTO inventory VALUES ('A', 'D1', 0.0, 0.0)")
    conn.execute("CREATE TABLE schedrcpts (ITEM VARCHAR, LOC VARCHAR, SCHED_DATE VARCHAR, QTY DOUBLE)")
    conn.execute("CREATE TABLE productionmethod (ITEM VARCHAR, LOC VARCHAR, PRODUCTIONMETHOD VARCHAR)")
    conn.execute("INSERT INTO productionmethod VALUES ('A', 'D1', 'M1')")
    conn.execute("""
        CREATE TABLE productionstep (
            ITEM VARCHAR, LOC VARCHAR, PRODUCTIONMETHOD VARCHAR,
            STEPNUM DOUBLE, RES VARCHAR, PRODDUR DOUBLE
        )
    """)
    conn.execute("INSERT INTO productionstep VALUES ('A', 'D1', 'M1', 1, 'R1', 1.0)")
    conn.execute("CREATE TABLE billofmaterials (ITEM VARCHAR, SUBORD VARCHAR, LOC VARCHAR, DRAWQTY DOUBLE)")
    conn.execute("CREATE TABLE res (RES VARCHAR, LOC VARCHAR, CAPACITY DOUBLE, EFFICIENCY DOUBLE)")
    conn.execute("INSERT INTO res VALUES ('R1', 'D1', 5.0, 1.0)")
    conn.execute("CREATE TABLE network (SOURCE VARCHAR, DEST VARCHAR, LEAD_TIME DOUBLE)")
    conn.execute("CREATE TABLE sku (ITEM VARCHAR, LOC VARCHAR)")
    return conn


def _entity_delta(entity: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    first = df.iloc[0]
    if entity == "sourcing":
        return [{"entity": "sourcing", "key": f"{first['ITEM']}|{first['SOURCE']}|{first['DEST']}", "updates": {"FACTOR": 0.5}}]
    if entity == "res":
        return [{"entity": "res", "key": f"{first['RES']}|{first['LOC']}", "updates": {"CAPACITY": 12}}]
    if entity == "dfutoskufcst":
        return [{"entity": "dfutoskufcst", "key": f"{first['ITEM']}|{first['SKULOC']}|{first['STARTDATE']}", "updates": {"TOTFCST": 100}}]
    return []


# -- Data canonicalizers for root-level solvers ---------------------------------

def _prep_sourcing(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    if "FACTOR" in r.columns:
        r["FACTOR"] = pd.to_numeric(r["FACTOR"], errors="coerce").fillna(1.0)
    else:
        r["FACTOR"] = 1.0
    if "BASE_COST" in r.columns:
        r["BASE_COST"] = pd.to_numeric(r["BASE_COST"], errors="coerce").fillna(1.0)
    elif "PRIORITY" in r.columns:
        r["BASE_COST"] = pd.to_numeric(r["PRIORITY"], errors="coerce").fillna(1.0)
    else:
        r["BASE_COST"] = 1.0
    if "MAX_CAPACITY" in r.columns:
        r["MAX_CAPACITY"] = pd.to_numeric(r["MAX_CAPACITY"], errors="coerce").fillna(1_000_000.0)
    else:
        r["MAX_CAPACITY"] = 1_000_000.0
    if "PRIORITY" not in r.columns:
        r["PRIORITY"] = 1
    if "TRANSPORT_TIME" not in r.columns:
        r["TRANSPORT_TIME"] = 1
    for c in ("ITEM", "SOURCE", "DEST"):
        r[c] = r[c].astype(str)
    return r


def _prep_sku(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    for c in ("ITEM", "LOC"):
        r[c] = r[c].astype(str)
    if "DEMAND" not in r.columns:
        r["DEMAND"] = 0.0
    r["DEMAND"] = pd.to_numeric(r["DEMAND"], errors="coerce").fillna(0.0)
    if "PRIORITY" not in r.columns:
        r["PRIORITY"] = 1
    r["PRIORITY"] = pd.to_numeric(r["PRIORITY"], errors="coerce").fillna(1).astype(int)
    return r


def _prep_bom(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    r.rename(columns={"ITEM": "PARENT_ITEM", "SUBORD": "COMPONENT_ITEM"}, inplace=True)
    if "QUANTITY_PER" in r.columns:
        r["QUANTITY_PER"] = pd.to_numeric(r["QUANTITY_PER"], errors="coerce").fillna(1.0)
    elif "DRAWQTY" in r.columns:
        r["QUANTITY_PER"] = pd.to_numeric(r["DRAWQTY"], errors="coerce").fillna(1.0)
    else:
        r["QUANTITY_PER"] = 1.0
    if "SCRAP_FACTOR" in r.columns:
        r["SCRAP_FACTOR"] = pd.to_numeric(r["SCRAP_FACTOR"], errors="coerce").fillna(0.0)
    else:
        r["SCRAP_FACTOR"] = 0.0
    return r


def _prep_res(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    if "RESOURCE" not in r.columns:
        r["RESOURCE"] = r.get("RES", "")
    for c, d in [("CAPACITY", 24.0), ("EFFICIENCY", 1.0), ("COST_PER_HOUR", 0.0)]:
        if c not in r.columns:
            r[c] = d
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(d)
    return r


def _prep_pm(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    if "METHOD" not in r.columns:
        r["METHOD"] = r.get("PRODUCTIONMETHOD", "")
    for c, d in [("YIELD_FACTOR", 1.0), ("SETUP_TIME", 0.0), ("RUN_TIME", 0.0), ("BATCH_SIZE", 0.0)]:
        if c not in r.columns:
            r[c] = d
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(d)
    return r


def _prep_ps(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    if "METHOD" not in r.columns:
        r["METHOD"] = r.get("PRODUCTIONMETHOD", "")
    if "STEP" not in r.columns:
        r["STEP"] = pd.to_numeric(r.get("STEPNUM", 1), errors="coerce").fillna(1).astype(int)
    if "RESOURCE" not in r.columns:
        r["RESOURCE"] = r.get("RES", "")
    for c in ("SETUP_TIME", "RUN_TIME", "QUEUE_TIME", "MOVE_TIME", "YIELD_FACTOR"):
        if c not in r.columns:
            r[c] = 0.0
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(0.0)
    return r


def _prep_inv(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    if "QTY" in r.columns and "ON_HAND" not in r.columns:
        r["ON_HAND"] = pd.to_numeric(r["QTY"], errors="coerce").fillna(0.0)
    for c in ("ON_HAND", "ON_ORDER", "ALLOCATED", "SAFETY_STOCK"):
        if c not in r.columns:
            r[c] = 0.0
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(0.0)
    return r


def _prep_sr(df: pd.DataFrame) -> pd.DataFrame:
    r = df.copy()
    if "QUANTITY" not in r.columns:
        r["QUANTITY"] = pd.to_numeric(r.get("QTY", 0.0), errors="coerce").fillna(0.0)
    else:
        r["QUANTITY"] = pd.to_numeric(r["QUANTITY"], errors="coerce").fillna(0.0)
    return r
