"""Backend smoke tests: Python module imports, DuckDB, Pydantic, Pyomo."""

import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

RESULTS: list[dict] = []

def record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0):
    RESULTS.append({"name": name, "passed": passed, "detail": detail, "elapsed_ms": elapsed_ms})

def test_import(module_name: str):
    t0 = time.perf_counter()
    try:
        importlib.import_module(module_name)
        record(f"import:{module_name}", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record(f"import:{module_name}", False, str(e), (time.perf_counter() - t0) * 1000)

def test_duckdb():
    t0 = time.perf_counter()
    try:
        import duckdb
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE t (id INT, name VARCHAR)")
        con.execute("INSERT INTO t VALUES (1, 'test')")
        row = con.execute("SELECT * FROM t").fetchone()
        con.close()
        assert row == (1, "test"), f"Unexpected row: {row}"
        record("duckdb:memory_ops", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("duckdb:memory_ops", False, str(e), (time.perf_counter() - t0) * 1000)

def test_pydantic_models():
    t0 = time.perf_counter()
    try:
        from models import ENTITY_SCHEMA_MAP
        assert len(ENTITY_SCHEMA_MAP) >= 20, f"Expected >=20 entities, got {len(ENTITY_SCHEMA_MAP)}"
        for name, schema in ENTITY_SCHEMA_MAP.items():
            assert hasattr(schema, "model_validate"), f"{name} missing model_validate"
        record("pydantic:entity_models", True, f"{len(ENTITY_SCHEMA_MAP)} models", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("pydantic:entity_models", False, str(e), (time.perf_counter() - t0) * 1000)

def test_pyomo_highs():
    t0 = time.perf_counter()
    try:
        import pyomo.environ as pyo
        m = pyo.ConcreteModel()
        m.x = pyo.Var(within=pyo.NonNegativeReals)
        m.obj = pyo.Objective(expr=m.x, sense=pyo.minimize)
        m.con = pyo.Constraint(expr=m.x >= 5)
        solver = pyo.SolverFactory("highs")
        result = solver.solve(m, tee=False)
        assert pyo.value(m.x) == 5.0, f"Expected x=5, got {pyo.value(m.x)}"
        record("pyomo:highs_solve", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("pyomo:highs_solve", False, str(e), (time.perf_counter() - t0) * 1000)

def test_polars_pandas_interop():
    t0 = time.perf_counter()
    try:
        import polars as pl
        import pandas as pd
        df_pl = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        df_pd = df_pl.to_pandas()
        df_pl2 = pl.from_pandas(df_pd)
        assert df_pl.shape == df_pl2.shape
        record("polars:pandas_interop", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("polars:pandas_interop", False, str(e), (time.perf_counter() - t0) * 1000)

def test_graph_service_import():
    t0 = time.perf_counter()
    try:
        from app.services.graph_service import GraphTopologySerializer
        record("service:graph_service_import", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("service:graph_service_import", False, str(e), (time.perf_counter() - t0) * 1000)

def test_simulation_runner_import():
    t0 = time.perf_counter()
    try:
        from app.services.simulation_runner import run_simulation
        record("service:simulation_runner_import", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("service:simulation_runner_import", False, str(e), (time.perf_counter() - t0) * 1000)

def test_optimizer_import():
    t0 = time.perf_counter()
    try:
        from optimizer import run_optimization
        record("module:optimizer_import", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("module:optimizer_import", False, str(e), (time.perf_counter() - t0) * 1000)

def run_all() -> list[dict]:
    core_imports = [
        "fastapi", "uvicorn", "pydantic", "duckdb", "pandas",
        "polars", "numpy", "pyomo", "highspy", "scipy",
        "httpx",
    ]
    app_imports = [
        "app", "app.api", "app.api.endpoints", "app.api.endpoints.graph",
        "app.core", "app.core.bulk_loader",
        "app.optimization", "app.optimization.demand_engine",
        "app.services", "app.services.graph_service",
        "app.services.simulation_runner", "app.services.by_exporter",
        "app.services.bottleneck_tracer", "app.services.mitigation_sandbox",
        "app.services.substitutions",
        "models", "schema_config", "file_parser", "optimizer",
    ]
    for mod in core_imports + app_imports:
        test_import(mod)
    test_duckdb()
    test_pydantic_models()
    test_pyomo_highs()
    test_polars_pandas_interop()
    test_graph_service_import()
    test_simulation_runner_import()
    test_optimizer_import()
    return RESULTS
