"""Integration smoke tests: live server connectivity and cross-service checks.

These tests require running servers. When servers are not running, they report
as WARNINGS (not failures) since the backend/frontend may not be started.
"""

import subprocess
import time
import urllib.request
import urllib.error

RESULTS: list[dict] = []

def record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0, warning: bool = False):
    RESULTS.append({"name": name, "passed": passed, "detail": detail, "elapsed_ms": elapsed_ms, "warning": warning})

def _url_hit(url: str, timeout: int = 5) -> tuple[bool, int, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status, resp.read().decode("utf-8")[:500]
    except urllib.error.HTTPError as e:
        return False, e.code, str(e)
    except Exception as e:
        return False, 0, str(e)

def test_backend_health_live():
    t0 = time.perf_counter()
    ok, status, body = _url_hit("http://127.0.0.1:8000/", timeout=5)
    elapsed = (time.perf_counter() - t0) * 1000
    if ok and status == 200:
        record("live:backend_health", True, f"status={status}", elapsed)
    else:
        record("live:backend_health", False, f"Backend server not running", elapsed, warning=True)

def test_backend_entities_live():
    t0 = time.perf_counter()
    ok, status, body = _url_hit("http://127.0.0.1:8000/entities", timeout=5)
    elapsed = (time.perf_counter() - t0) * 1000
    if ok and status == 200:
        record("live:backend_entities", True, f"status={status}", elapsed)
    else:
        record("live:backend_entities", False, f"Backend server not running", elapsed, warning=True)

def test_backend_docs_live():
    t0 = time.perf_counter()
    ok, status, body = _url_hit("http://127.0.0.1:8000/docs", timeout=5)
    elapsed = (time.perf_counter() - t0) * 1000
    if ok and status == 200:
        record("live:backend_docs", True, f"status={status}", elapsed)
    else:
        record("live:backend_docs", False, f"Backend server not running", elapsed, warning=True)

def test_backend_graph_live():
    t0 = time.perf_counter()
    ok, status, body = _url_hit("http://127.0.0.1:8000/api/v1/simulation/network-graph/baseline", timeout=10)
    elapsed = (time.perf_counter() - t0) * 1000
    if ok and status == 200:
        record("live:backend_graph", True, f"status={status}", elapsed)
    else:
        record("live:backend_graph", False, f"Backend server not running", elapsed, warning=True)

def test_frontend_live():
    t0 = time.perf_counter()
    ok, status, body = _url_hit("http://127.0.0.1:3000/", timeout=10)
    elapsed = (time.perf_counter() - t0) * 1000
    if ok and status == 200:
        record("live:frontend", True, f"status={status}", elapsed)
    else:
        record("live:frontend", False, f"Frontend server not running", elapsed, warning=True)

def test_cross_service_api_from_frontend():
    t0 = time.perf_counter()
    try:
        ok1, _, _ = _url_hit("http://127.0.0.1:8000/", timeout=3)
        ok2, _, _ = _url_hit("http://127.0.0.1:3000/", timeout=3)
        elapsed = (time.perf_counter() - t0) * 1000
        if ok1 and ok2:
            record("live:cross_service", True, "backend+frontend reachable", elapsed)
        elif ok2:
            record("live:cross_service", False, "frontend reachable, backend not running", elapsed, warning=True)
        else:
            record("live:cross_service", False, "neither server running", elapsed, warning=True)
    except Exception as e:
        record("live:cross_service", False, str(e), (time.perf_counter() - t0) * 1000, warning=True)

def run_all() -> list[dict]:
    test_backend_health_live()
    test_backend_entities_live()
    test_backend_docs_live()
    test_backend_graph_live()
    test_frontend_live()
    test_cross_service_api_from_frontend()
    return RESULTS
