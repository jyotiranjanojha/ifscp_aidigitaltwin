"""Solver smoke tests: Heuristic, LpOpt, Compare Both with real BY data."""

import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

RESULTS: list[dict] = []

BY_DATA_DIR = Path(r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658")

def record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0):
    RESULTS.append({"name": name, "passed": passed, "detail": detail, "elapsed_ms": elapsed_ms})

def _load_by_files() -> dict:
    files = {}
    if not BY_DATA_DIR.exists():
        return files
    for f in os.listdir(BY_DATA_DIR):
        if f.startswith("if_snop_") and f.endswith(".csv"):
            entity = f.split("_")[2].split("-")[0]
            with open(os.path.join(BY_DATA_DIR, f), "rb") as fh:
                files[entity] = (f, fh.read(), "text/csv")
    return files

def _build_form(files: dict) -> dict:
    return {entity: (name, io.BytesIO(content), ct) for entity, (name, content, ct) in files.items()}

def _assert_solver_result(data: dict, solver_name: str) -> bool:
    status = data.get("status")
    summary = data.get("summary") or {}
    shipments = data.get("shipments") or []
    method = data.get("method", "")

    has_summary = (
        summary.get("met_qty") is not None
        and summary.get("total_cost") is not None
        and summary.get("met_pct") is not None
    )
    has_shipments = len(shipments) > 0
    is_optimal = status in ("optimal", "infeasible")

    return has_summary and has_shipments and is_optimal

def run_all() -> list[dict]:
    try:
        from fastapi.testclient import TestClient
        from main import app
    except Exception as e:
        record("solver:client_init", False, str(e))
        return RESULTS

    client = TestClient(app)

    t0 = time.perf_counter()
    by_files = _load_by_files()
    elapsed = (time.perf_counter() - t0) * 1000
    if not by_files:
        record("solver:load_by_data", False, f"No BY files found at {BY_DATA_DIR}", elapsed)
        return RESULTS
    record("solver:load_by_data", True, f"{len(by_files)} files", elapsed)

    def test_solver(name: str, solver_param: str):
        t = time.perf_counter()
        try:
            r = client.post(f"/run-simulation/?solver={solver_param}", files=_build_form(by_files))
            elapsed_ms = (time.perf_counter() - t) * 1000
            if r.status_code != 200:
                record(f"solver:{name}", False, f"HTTP {r.status_code}: {r.text[:200]}", elapsed_ms)
                return
            data = r.json()
            passed = _assert_solver_result(data, name)
            s = data.get("summary") or {}
            detail = (
                f"method={data.get('method')} "
                f"met={s.get('met_qty')} "
                f"unmet={s.get('unmet_qty')} "
                f"cost={s.get('total_cost')} "
                f"shipments={len(data.get('shipments', []))}"
            )
            record(f"solver:{name}", passed, detail, elapsed_ms)
        except Exception as e:
            record(f"solver:{name}", False, str(e), (time.perf_counter() - t) * 1000)

    test_solver("heuristic", "heuristic")
    test_solver("lpopt", "lp")

    t = time.perf_counter()
    try:
        r_h = client.post("/run-simulation/?solver=heuristic", files=_build_form(by_files))
        r_lp = client.post("/run-simulation/?solver=lp", files=_build_form(by_files))
        elapsed_ms = (time.perf_counter() - t) * 1000
        if r_h.status_code == 200 and r_lp.status_code == 200:
            d_h = r_h.json()
            d_lp = r_lp.json()
            both_valid = _assert_solver_result(d_h, "heuristic") and _assert_solver_result(d_lp, "lp")
            h_cost = (d_h.get("summary") or {}).get("total_cost", 0)
            lp_cost = (d_lp.get("summary") or {}).get("total_cost", 0)
            record("solver:compare_both", both_valid, f"h_cost={h_cost} lp_cost={lp_cost}", elapsed_ms)
        else:
            record("solver:compare_both", False, f"heuristic={r_h.status_code} lp={r_lp.status_code}", elapsed_ms)
    except Exception as e:
        record("solver:compare_both", False, str(e), (time.perf_counter() - t) * 1000)

    return RESULTS
