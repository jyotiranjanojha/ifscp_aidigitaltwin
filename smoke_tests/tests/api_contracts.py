"""API contract smoke tests: endpoint response schemas and data shapes."""

import json
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
        record("api_contract:client_init", True, elapsed_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("api_contract:client_init", False, str(e), (time.perf_counter() - t0) * 1000)
        return RESULTS

    def assert_json_shape(path: str, label: str, required_keys: list[str] | None = None, method: str = "GET"):
        t = time.perf_counter()
        try:
            r = client.get(path) if method == "GET" else client.post(path)
            elapsed = (time.perf_counter() - t) * 1000
            assert r.status_code == 200, f"status={r.status_code}"
            data = r.json()
            assert isinstance(data, (dict, list)), f"Not dict/list: {type(data)}"
            if required_keys and isinstance(data, dict):
                missing = [k for k in required_keys if k not in data]
                assert not missing, f"Missing keys: {missing}"
            record(label, True, f"keys={list(data.keys())[:5] if isinstance(data, dict) else f'len={len(data)}'}", elapsed)
        except Exception as e:
            record(label, False, str(e), (time.perf_counter() - t) * 1000)

    assert_json_shape("/", "contract:health_check", ["status"])
    assert_json_shape("/entities", "contract:entities_list")
    assert_json_shape("/api/v1/simulation/network-graph/baseline", "contract:network_graph", ["nodes", "edges", "summary"])
    assert_json_shape("/api/v1/simulation/bom-graph/FAKE_ITEM", "contract:bom_graph", ["nodes", "edges"])

    t = time.perf_counter()
    try:
        r = client.get("/api/v1/simulation/network-graph/baseline")
        data = r.json()
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        summary = data.get("summary", {})
        assert isinstance(nodes, list), f"nodes not list: {type(nodes)}"
        assert isinstance(edges, list), f"edges not list: {type(edges)}"
        assert isinstance(summary, dict), f"summary not dict: {type(summary)}"
        if nodes:
            node = nodes[0]
            assert "id" in node, "Node missing 'id'"
            assert "type" in node, "Node missing 'type'"
            assert "label" in node, "Node missing 'label'"
        if edges:
            edge = edges[0]
            assert "source" in edge, "Edge missing 'source'"
            assert "target" in edge, "Edge missing 'target'"
            assert "baseline_volume" in edge, "Edge missing 'baseline_volume'"
        elapsed = (time.perf_counter() - t) * 1000
        record("contract:graph_schema", True, f"{len(nodes)} nodes, {len(edges)} edges", elapsed)
    except Exception as e:
        record("contract:graph_schema", False, str(e), (time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    try:
        r = client.get("/api/v1/simulation/bom-graph/FAKE_ITEM")
        data = r.json()
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        assert isinstance(nodes, list) and isinstance(edges, list)
        elapsed = (time.perf_counter() - t) * 1000
        record("contract:bom_graph_schema", True, f"{len(nodes)} nodes, {len(edges)} edges", elapsed)
    except Exception as e:
        record("contract:bom_graph_schema", False, str(e), (time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    try:
        r = client.get("/openapi.json")
        schema = r.json()
        paths = schema.get("paths", {})
        components = schema.get("components", {}).get("schemas", {})
        assert len(paths) >= 5, f"Expected >=5 paths, got {len(paths)}"
        elapsed = (time.perf_counter() - t) * 1000
        record("contract:openapi_structure", True, f"{len(paths)} paths, {len(components)} schemas", elapsed)
    except Exception as e:
        record("contract:openapi_structure", False, str(e), (time.perf_counter() - t) * 1000)

    return RESULTS
