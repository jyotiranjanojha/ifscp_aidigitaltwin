#!/usr/bin/env python3
"""
Environment verification script for Blue Yonder Supply Chain Digital Twin backend.

Checks:
1. Core Python package imports
2. Pyomo + HiGHS solver connectivity via APPSI
3. DuckDB in-memory operations
"""

import sys
import subprocess
from typing import Tuple, List


def check_import(module_name: str, display_name: str = None) -> Tuple[bool, str]:
    """Try importing a module and return (success, message)."""
    name = display_name or module_name
    try:
        __import__(module_name)
        return True, f"[OK] {name}"
    except ImportError as e:
        return False, f"[FAIL] {name}: {e}"


def check_pyomo_highs() -> Tuple[bool, str]:
    """Verify Pyomo can construct a model and solve with HiGHS via APPSI."""
    try:
        import pyomo.environ as pyo
        from pyomo.contrib.appsi.solvers import Highs
        from pyomo.contrib.appsi.base import TerminationCondition as AppsiTerminationCondition
    except ImportError as e:
        return False, f"[FAIL] Pyomo/APPSI import: {e}"

    try:
        model = pyo.ConcreteModel()
        model.x = pyo.Var(domain=pyo.NonNegativeReals)
        model.obj = pyo.Objective(expr=model.x, sense=pyo.minimize)
        model.con = pyo.Constraint(expr=model.x >= 5.0)

        solver = Highs()
        result = solver.solve(model)

        if result.termination_condition == AppsiTerminationCondition.optimal:
            val = pyo.value(model.x)
            if abs(val - 5.0) < 1e-6:
                return True, f"[OK] Pyomo + HiGHS (APPSI) - solved min x s.t. x>=5, got x={val:.4f}"
            return False, f"[FAIL] Pyomo + HiGHS: unexpected solution x={val}"
        return False, f"[FAIL] Pyomo + HiGHS: non-optimal termination {result.termination_condition}"
    except Exception as e:
        return False, f"[FAIL] Pyomo + HiGHS solve error: {e}"


def check_duckdb() -> Tuple[bool, str]:
    """Verify DuckDB in-memory table creation and query."""
    try:
        import duckdb
    except ImportError as e:
        return False, f"[FAIL] DuckDB import: {e}"

    try:
        con = duckdb.connect(':memory:')
        con.execute("CREATE TABLE test (id INTEGER, name VARCHAR, value DOUBLE)")
        con.execute("INSERT INTO test VALUES (1, 'item_a', 100.5), (2, 'item_b', 200.25)")
        result = con.execute("SELECT COUNT(*), SUM(value) FROM test").fetchone()

        if result and result[0] == 2 and abs(result[1] - 300.75) < 1e-6:
            con.close()
            return True, f"[OK] DuckDB - created table, inserted 2 rows, sum={result[1]}"
        con.close()
        return False, f"[FAIL] DuckDB: unexpected query result {result}"
    except Exception as e:
        return False, f"[FAIL] DuckDB operation error: {e}"


def check_polars_pandas() -> Tuple[bool, str]:
    """Quick polars and pandas DataFrame sanity check."""
    try:
        import polars as pl
        import pandas as pd
    except ImportError as e:
        return False, f"[FAIL] Polars/Pandas import: {e}"

    try:
        df_pl = pl.DataFrame({"sku": ["A", "B"], "demand": [100, 200]})
        df_pd = df_pl.to_pandas()
        total = df_pd["demand"].sum()
        if total == 300:
            return True, f"[OK] Polars + Pandas interop - sum(demand)={total}"
        return False, f"[FAIL] Polars/Pandas: unexpected sum {total}"
    except Exception as e:
        return False, f"[FAIL] Polars/Pandas operation: {e}"


def main() -> int:
    print("=" * 70)
    print("Blue Yonder Supply Chain Digital Twin - Environment Verification")
    print("=" * 70)
    print()

    checks: List[Tuple[bool, str]] = []

    # Core imports
    print("1. Core Package Imports")
    print("-" * 40)
    for module, display in [
        ("fastapi", "FastAPI"),
        ("pydantic", "Pydantic"),
        ("pydantic_settings", "Pydantic Settings"),
        ("uvicorn", "Uvicorn"),
        ("duckdb", "DuckDB"),
        ("polars", "Polars"),
        ("pandas", "Pandas"),
        ("numpy", "NumPy"),
        ("pyomo", "Pyomo"),
        ("highspy", "HiGHS (highspy)"),
        ("scipy", "SciPy"),
    ]:
        ok, msg = check_import(module, display)
        checks.append((ok, msg))
        print(f"  {msg}")

    print()
    print("2. Solver & Data Engine Functional Tests")
    print("-" * 40)

    # Pyomo + HiGHS
    ok, msg = check_pyomo_highs()
    checks.append((ok, msg))
    print(f"  {msg}")

    # DuckDB
    ok, msg = check_duckdb()
    checks.append((ok, msg))
    print(f"  {msg}")

    # Polars + Pandas
    ok, msg = check_polars_pandas()
    checks.append((ok, msg))
    print(f"  {msg}")

    print()
    print("=" * 70)
    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    print(f"SUMMARY: {passed}/{total} checks passed")
    print("=" * 70)

    if passed == total:
        print("\nAll systems operational. Backend ready for development.\n")
        return 0
    else:
        print(f"\n{total - passed} check(s) failed. Install missing dependencies:\n")
        print("  pip install -r requirements.txt\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())