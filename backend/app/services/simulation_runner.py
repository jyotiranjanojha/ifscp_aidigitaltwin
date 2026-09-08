from __future__ import annotations

from typing import Any, Literal, Optional

import duckdb

from app.optimization.heuristic_engine import run_heuristic_supply_planning
from lpopt_engine import run_lp_optimization


SolverType = Literal["heuristic", "lpopt", "compare_both"]

_SCENARIO_CONNECTIONS: dict[str, duckdb.DuckDBPyConnection] = {}


def register_scenario_connection(scenario_id: str, conn: duckdb.DuckDBPyConnection) -> None:
    _SCENARIO_CONNECTIONS[scenario_id] = conn


def unregister_scenario_connection(scenario_id: str) -> None:
    _SCENARIO_CONNECTIONS.pop(scenario_id, None)


def run_simulation(
    scenario_id: str,
    solver_type: SolverType = "heuristic",
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    scenario_conn = conn or _SCENARIO_CONNECTIONS.get(scenario_id)
    if scenario_conn is None:
        raise ValueError(f"No DuckDB connection registered for scenario_id '{scenario_id}'")

    if solver_type == "heuristic":
        return run_heuristic_supply_planning(scenario_conn, **kwargs)

    if solver_type == "lpopt":
        return _run_lpopt(scenario_conn, **kwargs)

    if solver_type == "compare_both":
        heuristic_result = run_heuristic_supply_planning(scenario_conn, **kwargs)
        lpopt_result = _run_lpopt(scenario_conn, **kwargs)
        return {
            "scenario_id": scenario_id,
            "solver_type": solver_type,
            "heuristic": heuristic_result,
            "lpopt": lpopt_result,
        }

    raise ValueError(f"Unsupported solver_type '{solver_type}'")


def _run_lpopt(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> dict[str, Any]:
    sourcing_df = _required_table(conn, "sourcing")
    sku_df = _required_table(conn, "sku")
    return run_lp_optimization(
        sourcing_df=sourcing_df,
        sku_df=sku_df,
        risk_adjustments=kwargs.get("risk_adjustments", {}),
        bom_df=_optional_table(conn, "billofmaterials"),
        res_df=_optional_table(conn, "res"),
        productionmethod_df=_optional_table(conn, "productionmethod"),
        productionstep_df=_optional_table(conn, "productionstep"),
        inventory_df=_optional_table(conn, "inventory"),
        schedrcpts_df=_optional_table(conn, "schedrcpts"),
    )


def _required_table(conn: duckdb.DuckDBPyConnection, table_name: str):
    df = _optional_table(conn, table_name)
    if df is None:
        raise ValueError(f"DuckDB scenario is missing required table '{table_name}'")
    return df


def _optional_table(conn: duckdb.DuckDBPyConnection, table_name: str):
    exists = conn.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE lower(table_name) = ?
        """,
        [table_name.lower()],
    ).fetchone()[0]
    if not exists:
        return None
    df = conn.execute(f'SELECT * FROM "{table_name}"').fetchdf()
    df.columns = [str(column).strip().upper() for column in df.columns]
    return df