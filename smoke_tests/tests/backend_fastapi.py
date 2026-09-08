"""Backend smoke tests: FastAPI TestClient endpoint checks."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

RESULTS: list[dict] = []

def record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0):
    RESULTS.append({"name": name, "passed": passed, "detail": detail, "elapsed_ms": elapsed_ms})

def run_all() -> list[dict]:
    t0 = time.perf_counter()
    try:
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        record("fastapi:testclient_init", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("fastapi:testclient_init", False, str(e), (time.perf_counter() - t0) * 1000)
        return RESULTS

    def hit(method: str, path: str, expected_status: int, label: str, check_json: bool = True):
        t = time.perf_counter()
        try:
            if method == "GET":
                r = client.get(path)
            elif method == "POST":
                r = client.post(path)
            else:
                record(label, False, f"Unsupported method {method}")
                return
            elapsed = (time.perf_counter() - t) * 1000
            passed = r.status_code == expected_status
            detail = f"status={r.status_code}"
            if check_json:
                try:
                    r.json()
                    detail += " json=ok"
                except Exception:
                    detail += " json=invalid"
                    passed = False
            record(label, passed, detail, elapsed)
        except Exception as e:
            record(label, False, str(e), (time.perf_counter() - t) * 1000)

    hit("GET", "/", 200, "api:health_check")
    hit("GET", "/entities", 200, "api:entities_list")
    hit("GET", "/docs", 200, "api:swagger_docs", check_json=False)
    hit("GET", "/openapi.json", 200, "api:openapi_schema")
    hit("GET", "/api/v1/simulation/network-graph/nonexistent", 200, "api:network_graph_fallback")
    hit("GET", "/api/v1/simulation/bom-graph/FAKE_ITEM", 200, "api:bom_graph_fallback")

    t = time.perf_counter()
    try:
        r = client.get("/openapi.json")
        schema = r.json()
        paths = list(schema.get("paths", {}).keys())
        assert len(paths) >= 5, f"Expected >=5 paths, got {len(paths)}: {paths}"
        record("api:openapi_paths_count", True, f"{len(paths)} paths", (time.perf_counter() - t) * 1000)
    except Exception as e:
        record("api:openapi_paths_count", False, str(e), (time.perf_counter() - t) * 1000)

    return RESULTS
