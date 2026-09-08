from __future__ import annotations

import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import polars as pl
import pyomo.environ as pyo
import pytest
from pyomo.contrib.appsi.solvers.highs import Highs as HiGHS
from pyomo.core.expr.numvalue import is_potentially_variable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import ENTITY_SCHEMA_MAP  # noqa: E402


DEFAULT_DATA_DIR = Path(
    r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658"
)
FILE_PATTERN = re.compile(r"^if_snop_([a-z]+)-20251013\d*\.csv$", re.IGNORECASE)
LANE_CAPACITY_DEFAULT = 1_000_000.0
RESOURCE_CAPACITY_DEFAULT = 24.0
UNMET_PENALTY_PER_UNIT = 1_000_000.0


@dataclass(frozen=True)
class SolverBenchmark:
    termination_status: str
    solve_time_seconds: float
    total_landed_cost: float
    fulfillment_rate_pct: float
    top_resources: list[tuple[str, str, float, float, float]]
    top_lanes: list[tuple[str, str, str, str, float, float]]


def test_real_by_data_lp_solver_benchmark(capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = _resolve_data_dir()
    tables = _load_real_by_tables(data_dir)
    conn = _load_duckdb_tables(tables)
    polars_tables = {name: pl.DataFrame(df.to_dict(orient="list"), strict=False) for name, df in tables.items()}
    assert len(polars_tables) == len(tables)

    model_data = _build_model_data(conn, tables)
    model = _build_pyomo_model(model_data)

    solver = HiGHS()
    start = time.perf_counter()
    result = solver.solve(model)
    solve_time = time.perf_counter() - start
    termination = getattr(result.termination_condition, "name", str(result.termination_condition)).lower()

    benchmark = _collect_benchmark(model, model_data, termination, solve_time)
    report = _format_solver_report(data_dir, benchmark)
    with capsys.disabled():
        print(report)

    assert termination in {"optimal", "feasible"}, report
    assert benchmark.fulfillment_rate_pct >= 0.0, report


def _resolve_data_dir() -> Path:
    data_dir = Path(os.environ.get("BY_DATA_DIR", DEFAULT_DATA_DIR))
    if not data_dir.exists() or not data_dir.is_dir():
        pytest.fail(f"BY data directory does not exist or is not a directory: {data_dir}")
    return data_dir


def _load_real_by_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for csv_path in sorted(data_dir.glob("if_snop_*-20251013*.csv")):
        match = FILE_PATTERN.match(csv_path.name)
        if not match:
            continue
        entity = match.group(1).lower()
        if entity not in ENTITY_SCHEMA_MAP:
            continue
        tables[entity] = _read_by_csv(csv_path)

    missing = sorted(set(ENTITY_SCHEMA_MAP) - set(tables))
    if missing:
        pytest.fail(f"Missing BY files for entities: {', '.join(missing)}")
    return tables


def _read_by_csv(csv_path: Path) -> pd.DataFrame:
    content = csv_path.read_bytes()
    header = content.splitlines()[0].decode("utf-8-sig", errors="ignore") if content else ""
    delimiter = max(["|", ",", "\t", ";"], key=header.count)
    df = pd.read_csv(csv_path, sep=delimiter)
    df.columns = [_normalize_column_name(column) for column in df.columns]
    return df


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


def _load_duckdb_tables(tables: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    for entity, df in tables.items():
        conn.register(f"{entity}_df", df)
        conn.execute(f'CREATE TABLE "{entity}" AS SELECT * FROM "{entity}_df"')
        conn.unregister(f"{entity}_df")
    return conn


def _build_model_data(conn: duckdb.DuckDBPyConnection, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    forecast_demand = conn.execute(
        '''
        SELECT
            CAST(ITEM AS VARCHAR) AS ITEM,
            CAST(SKULOC AS VARCHAR) AS LOC,
            CAST(STARTDATE AS VARCHAR) AS PERIOD,
            SUM(CAST(TOTFCST AS DOUBLE)) AS DEMAND_QTY
        FROM dfutoskufcst
        GROUP BY 1, 2, 3
        '''
    ).fetchdf()
    customer_demand = conn.execute(
        '''
        SELECT
            CAST(ITEM AS VARCHAR) AS ITEM,
            CAST(LOC AS VARCHAR) AS LOC,
            COALESCE(
                CAST(DELRDD_CALC_DT AS VARCHAR),
                CAST(GI_DT AS VARCHAR),
                CAST(U_CGID_DT AS VARCHAR),
                CAST(U_RGID_DT AS VARCHAR),
                CAST(U_CREATION_DT AS VARCHAR)
            ) AS PERIOD,
            SUM(CAST(QTY AS DOUBLE)) AS DEMAND_QTY
        FROM customerorder
        GROUP BY 1, 2, 3
        '''
    ).fetchdf()
    demand_df = pd.concat([forecast_demand, customer_demand], ignore_index=True)
    demand_df["PERIOD"] = demand_df["PERIOD"].map(_period_bucket)
    demand_df["DEMAND_QTY"] = pd.to_numeric(demand_df["DEMAND_QTY"], errors="coerce").fillna(0.0)
    demand_df = demand_df.groupby(["ITEM", "LOC", "PERIOD"], as_index=False)["DEMAND_QTY"].sum()

    sourcing_df = tables["sourcing"].copy()
    sourcing_df["FACTOR"] = pd.to_numeric(sourcing_df.get("FACTOR", 1.0), errors="coerce").fillna(1.0)
    sourcing_df["PRIORITY"] = pd.to_numeric(sourcing_df.get("PRIORITY", 1.0), errors="coerce").fillna(1.0)

    inventory_df = tables["inventory"].copy()
    inventory_df["QTY"] = pd.to_numeric(inventory_df.get("QTY", 0.0), errors="coerce").fillna(0.0)
    inventory = defaultdict(float)
    for row in inventory_df.to_dict(orient="records"):
        inventory[(str(row["ITEM"]), str(row["LOC"]))] += float(row["QTY"])

    sched_df = tables["schedrcpts"].copy()
    sched_df["QTY"] = pd.to_numeric(sched_df.get("QTY", 0.0), errors="coerce").fillna(0.0)
    scheduled_receipts = defaultdict(float)
    for row in sched_df.to_dict(orient="records"):
        scheduled_receipts[(str(row["ITEM"]), str(row["LOC"]), _period_bucket(row.get("SCHED_DATE")))] += float(row["QTY"])

    production_methods = _production_methods(tables["productionmethod"].copy())
    production_steps = _production_steps(tables["productionstep"].copy())
    bom_links = _bom_links(tables["billofmaterials"].copy())
    resource_capacity = _resource_capacity(tables["res"].copy())

    periods = sorted(set(demand_df["PERIOD"]) | {period for *_prefix, period in scheduled_receipts})
    if not periods:
        pytest.fail("No demand periods found from dfutoskufcst or customerorder")

    demand = {
        (str(row["ITEM"]), str(row["LOC"]), str(row["PERIOD"])): float(row["DEMAND_QTY"])
        for row in demand_df.to_dict(orient="records")
        if float(row["DEMAND_QTY"]) > 0
    }
    lanes = [
        (str(row["ITEM"]), str(row["SOURCE"]), str(row["DEST"]))
        for row in sourcing_df.to_dict(orient="records")
    ]
    lane_cost = {
        (str(row["ITEM"]), str(row["SOURCE"]), str(row["DEST"])): max(float(row["PRIORITY"]), 1.0)
        for row in sourcing_df.to_dict(orient="records")
    }
    lane_capacity = {
        (str(row["ITEM"]), str(row["SOURCE"]), str(row["DEST"]), period): max(float(row["FACTOR"]), 0.0) * LANE_CAPACITY_DEFAULT
        for row in sourcing_df.to_dict(orient="records")
        for period in periods
    }

    return {
        "periods": periods,
        "demand": demand,
        "demand_keys": sorted(demand),
        "items": sorted(set(demand_df["ITEM"].astype(str)) | set(sourcing_df["ITEM"].astype(str))),
        "locations": sorted(set(demand_df["LOC"].astype(str)) | set(sourcing_df["SOURCE"].astype(str)) | set(sourcing_df["DEST"].astype(str))),
        "lanes": sorted(set(lanes)),
        "lane_cost": lane_cost,
        "lane_capacity": lane_capacity,
        "inventory": inventory,
        "scheduled_receipts": scheduled_receipts,
        "production_methods": production_methods,
        "production_steps": production_steps,
        "bom_links": bom_links,
        "resource_capacity": resource_capacity,
        "resources": sorted(resource_capacity),
    }


def _production_methods(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    return sorted({(str(row["ITEM"]), str(row["LOC"]), str(row["PRODUCTIONMETHOD"])) for row in df.to_dict(orient="records")})


def _production_steps(df: pd.DataFrame) -> dict[tuple[str, str, str], list[tuple[str, float]]]:
    result: dict[tuple[str, str, str], list[tuple[str, float]]] = defaultdict(list)
    df["PRODDUR"] = pd.to_numeric(df.get("PRODDUR", 0.0), errors="coerce").fillna(0.0)
    for row in df.to_dict(orient="records"):
        resource = row.get("RES")
        if pd.isna(resource) or str(resource).strip() == "":
            continue
        key = (str(row["ITEM"]), str(row["LOC"]), str(row["PRODUCTIONMETHOD"]))
        result[key].append((str(resource), max(float(row["PRODDUR"]), 0.0)))
    return result


def _bom_links(df: pd.DataFrame) -> dict[tuple[str, str], list[tuple[str, float]]]:
    result: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    df["DRAWQTY"] = pd.to_numeric(df.get("DRAWQTY", 0.0), errors="coerce").fillna(0.0)
    for row in df.to_dict(orient="records"):
        result[(str(row["ITEM"]), str(row["LOC"]))].append((str(row["SUBORD"]), max(float(row["DRAWQTY"]), 0.0)))
    return result


def _resource_capacity(df: pd.DataFrame) -> dict[tuple[str, str], float]:
    result = {}
    for row in df.to_dict(orient="records"):
        result[(str(row["RES"]), str(row["LOC"]))] = RESOURCE_CAPACITY_DEFAULT
    return result


def _build_pyomo_model(data: dict[str, Any]) -> pyo.ConcreteModel:
    model = pyo.ConcreteModel()
    model.LANES = pyo.Set(initialize=data["lanes"], dimen=3)
    model.PERIODS = pyo.Set(initialize=data["periods"])
    model.DEMAND_KEYS = pyo.Set(initialize=data["demand_keys"], dimen=3)
    model.PROD_KEYS = pyo.Set(initialize=data["production_methods"], dimen=3)
    model.RESOURCES = pyo.Set(initialize=data["resources"], dimen=2)

    model.ship = pyo.Var(model.LANES, model.PERIODS, domain=pyo.NonNegativeReals)
    model.unmet = pyo.Var(model.DEMAND_KEYS, domain=pyo.NonNegativeReals)
    model.produce = pyo.Var(model.PROD_KEYS, model.PERIODS, domain=pyo.NonNegativeReals)

    def objective_rule(m):
        shipment_cost = sum(
            m.ship[item, source, dest, period] * data["lane_cost"].get((item, source, dest), 1.0)
            for item, source, dest in m.LANES
            for period in m.PERIODS
        )
        production_cost = sum(m.produce[item, loc, method, period] * 0.1 for item, loc, method in m.PROD_KEYS for period in m.PERIODS)
        unmet_cost = sum(m.unmet[key] * UNMET_PENALTY_PER_UNIT for key in m.DEMAND_KEYS)
        return shipment_cost + production_cost + unmet_cost

    model.total_cost = pyo.Objective(rule=objective_rule, sense=pyo.minimize)

    def lane_capacity_rule(m, item, source, dest, period):
        return m.ship[item, source, dest, period] <= data["lane_capacity"].get((item, source, dest, period), 0.0)

    model.lane_capacity_constraint = pyo.Constraint(model.LANES, model.PERIODS, rule=lane_capacity_rule)

    def demand_rule(m, item, loc, period):
        inbound = sum(m.ship[l_item, source, dest, p] for l_item, source, dest in m.LANES for p in m.PERIODS if l_item == item and dest == loc and p == period)
        produced = sum(m.produce[p_item, p_loc, method, p] for p_item, p_loc, method in m.PROD_KEYS for p in m.PERIODS if p_item == item and p_loc == loc and p == period)
        available = data["inventory"].get((item, loc), 0.0) + data["scheduled_receipts"].get((item, loc, period), 0.0)
        return inbound + produced + available + m.unmet[item, loc, period] >= data["demand"].get((item, loc, period), 0.0)

    model.demand_constraint = pyo.Constraint(model.DEMAND_KEYS, rule=demand_rule)

    def resource_capacity_rule(m, resource, loc, period):
        usage = 0
        for prod_key, steps in data["production_steps"].items():
            item, prod_loc, method = prod_key
            if prod_loc != loc:
                continue
            for step_resource, hours_per_unit in steps:
                if step_resource == resource:
                    usage += m.produce[item, prod_loc, method, period] * hours_per_unit
        cap = data["resource_capacity"].get((resource, loc), RESOURCE_CAPACITY_DEFAULT)
        if not is_potentially_variable(usage):
            return pyo.Constraint.Feasible if usage <= cap else pyo.Constraint.Infeasible
        return usage <= cap

    model.resource_capacity_constraint = pyo.Constraint(model.RESOURCES, model.PERIODS, rule=resource_capacity_rule)

    bom_parent_locs = sorted(data["bom_links"])
    model.BOM_PARENT_LOCS = pyo.Set(initialize=bom_parent_locs, dimen=2)

    def bom_explosion_rule(m, parent_item, loc, period):
        component_required = sum(
            m.produce[parent_item, loc, method, period] * qty_per
            for item, prod_loc, method in m.PROD_KEYS
            for component, qty_per in data["bom_links"].get((parent_item, loc), [])
            if item == parent_item and prod_loc == loc
        )
        available_components = sum(data["inventory"].get((component, loc), 0.0) for component, _qty_per in data["bom_links"].get((parent_item, loc), []))
        if not is_potentially_variable(component_required):
            return pyo.Constraint.Feasible if component_required <= available_components else pyo.Constraint.Infeasible
        return component_required <= available_components

    model.bom_explosion_constraint = pyo.Constraint(model.BOM_PARENT_LOCS, model.PERIODS, rule=bom_explosion_rule)
    return model


def _collect_benchmark(
    model: pyo.ConcreteModel,
    data: dict[str, Any],
    termination: str,
    solve_time: float,
) -> SolverBenchmark:
    total_demand = sum(data["demand"].values())
    total_unmet = sum(pyo.value(model.unmet[key]) for key in model.DEMAND_KEYS)
    fulfilled = max(total_demand - total_unmet, 0.0)
    fulfillment_rate = (fulfilled / total_demand) * 100.0 if total_demand else 0.0
    total_landed_cost = pyo.value(model.total_cost) - (total_unmet * UNMET_PENALTY_PER_UNIT)

    resource_rows = []
    for resource, loc in model.RESOURCES:
        for period in model.PERIODS:
            used = sum(
                pyo.value(model.produce[item, prod_loc, method, period]) * hours_per_unit
                for (item, prod_loc, method), steps in data["production_steps"].items()
                if prod_loc == loc
                for step_resource, hours_per_unit in steps
                if step_resource == resource
            )
            cap = data["resource_capacity"].get((resource, loc), RESOURCE_CAPACITY_DEFAULT)
            if used > 1e-6:
                resource_rows.append((resource, loc, float(period), used, (used / cap) * 100.0 if cap else 0.0))

    lane_rows = []
    for item, source, dest in model.LANES:
        for period in model.PERIODS:
            qty = pyo.value(model.ship[item, source, dest, period])
            if qty > 1e-6:
                lane_rows.append((item, source, dest, str(period), qty, qty * data["lane_cost"].get((item, source, dest), 1.0)))

    return SolverBenchmark(
        termination_status=termination,
        solve_time_seconds=solve_time,
        total_landed_cost=total_landed_cost,
        fulfillment_rate_pct=fulfillment_rate,
        top_resources=sorted(resource_rows, key=lambda row: row[4], reverse=True)[:5],
        top_lanes=sorted(lane_rows, key=lambda row: row[5], reverse=True)[:5],
    )


def _format_solver_report(data_dir: Path, benchmark: SolverBenchmark) -> str:
    lines = [
        "",
        "Real BY Solver Benchmark",
        f"Data directory: {data_dir}",
        f"Termination status: {benchmark.termination_status}",
        f"Solve time seconds: {benchmark.solve_time_seconds:.4f}",
        f"Total landed cost: {benchmark.total_landed_cost:,.2f}",
        f"Demand fulfillment rate: {benchmark.fulfillment_rate_pct:.2f}%",
        "",
        "Top 5 Bottlenecked Resources",
        _format_table(
            ["RES", "LOC", "PERIOD", "USED", "UTIL %"],
            [[res, loc, str(period), f"{used:,.2f}", f"{util:.2f}%"] for res, loc, period, used, util in benchmark.top_resources],
        ),
        "",
        "Top 5 Highest-Cost Sourcing Lanes",
        _format_table(
            ["ITEM", "SOURCE", "DEST", "PERIOD", "QTY", "COST"],
            [[item, source, dest, period, f"{qty:,.2f}", f"{cost:,.2f}"] for item, source, dest, period, qty, cost in benchmark.top_lanes],
        ),
    ]
    return "\n".join(lines)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        rows = [["-" for _ in headers]]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    separator = "-+-".join("-" * width for width in widths)
    formatted = [" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)), separator]
    formatted.extend(" | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rows)
    return "\n".join(formatted)


def _period_bucket(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return "UNDATED"
    return parsed.date().isoformat()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.environ["BY_DATA_DIR"] = sys.argv[1]
        sys.argv = [sys.argv[0], "-s", sys.argv[0]]
    raise SystemExit(pytest.main(sys.argv[1:] or ["-s", __file__]))