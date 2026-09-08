"""Unified smoke test runner for sp_digitaltwin.

Usage:
    python smoke_tests/runner.py              # Run all tests
    python smoke_tests/runner.py --backend    # Backend-only tests
    python smoke_tests/runner.py --frontend   # Frontend-only tests
    python smoke_tests/runner.py --live       # Live integration tests only
    python smoke_tests/runner.py --quick      # Skip slow tests (tsc, build)
"""

import argparse
import importlib
import sys
import time
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def color(text: str, code: str) -> str:
    if sys.stdout.isatty():
        return f"{code}{text}{RESET}"
    return text

def print_header(title: str):
    width = 72
    print()
    print(color("=" * width, CYAN))
    print(color(f"  {title}", BOLD))
    print(color("=" * width, CYAN))

def print_suite(name: str):
    print()
    print(color(f"--- {name} ---", BOLD))

def print_result(r: dict):
    if r.get("warning"):
        icon = color("WARN", YELLOW)
    elif r["passed"]:
        icon = color("PASS", GREEN)
    else:
        icon = color("FAIL", RED)
    ms = f" ({r['elapsed_ms']:.0f}ms)" if r.get("elapsed_ms") else ""
    detail = f" -- {r['detail']}" if r.get("detail") else ""
    print(f"  [{icon}] {r['name']}{ms}{detail}")

def print_summary(all_results: list[dict], elapsed_s: float):
    passed = sum(1 for r in all_results if r["passed"])
    failed = sum(1 for r in all_results if not r["passed"] and not r.get("warning"))
    warnings = sum(1 for r in all_results if r.get("warning"))
    total = len(all_results)
    status = color("ALL PASSED", GREEN) if failed == 0 else color(f"{failed} FAILED", RED)

    print()
    print(color("=" * 72, CYAN))
    print(color(f"  SMOKE TEST SUMMARY", BOLD))
    print(color("=" * 72, CYAN))
    print(f"  Total:    {total}")
    print(f"  Passed:   {color(str(passed), GREEN)}")
    print(f"  Failed:   {color(str(failed), RED)}")
    if warnings:
        print(f"  Warnings: {color(str(warnings), YELLOW)} (servers not running)")
    print(f"  Time:     {elapsed_s:.1f}s")
    print(f"  Status:   {status}")
    print(color("=" * 72, CYAN))

    if failed:
        print()
        print(color("  FAILURES:", RED))
        for r in all_results:
            if not r["passed"] and not r.get("warning"):
                detail = f" -- {r['detail']}" if r.get("detail") else ""
                print(f"    {color('FAIL', RED)} {r['name']}{detail}")

    return failed == 0

def save_report(all_results: list[dict], elapsed_s: float, args):
    import json
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(elapsed_s, 2),
        "total": len(all_results),
        "passed": sum(1 for r in all_results if r["passed"]),
        "failed": sum(1 for r in all_results if not r["passed"] and not r.get("warning")),
        "warnings": sum(1 for r in all_results if r.get("warning")),
        "mode": "all",
        "results": all_results,
    }
    report_path = RESULTS_DIR / f"smoke_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved: {report_path}")
    return report_path

def load_suite(module_name: str):
    mod = importlib.import_module(f"smoke_tests.tests.{module_name}")
    return mod.run_all

def main():
    parser = argparse.ArgumentParser(description="sp_digitaltwin smoke test runner")
    parser.add_argument("--backend", action="store_true", help="Run backend-only tests")
    parser.add_argument("--frontend", action="store_true", help="Run frontend-only tests")
    parser.add_argument("--live", action="store_true", help="Run live integration tests only")
    parser.add_argument("--quick", action="store_true", help="Skip slow tests (tsc, build)")
    args = parser.parse_args()

    print_header("sp_digitaltwin Smoke Test Suite")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'backend' if args.backend else 'frontend' if args.frontend else 'live' if args.live else 'quick' if args.quick else 'all'}")

    all_results = []
    start = time.perf_counter()

    suites = []

    if args.live:
        suites = [("integration", "Integration (Live Servers)")]
    elif args.backend:
        suites = [
            ("backend_imports", "Backend Imports & DuckDB"),
            ("backend_fastapi", "Backend FastAPI Endpoints"),
            ("api_contracts", "API Contract Validation"),
            ("solver_checks", "Solver End-to-End (Heuristic/LpOpt/Compare)"),
        ]
    elif args.frontend:
        suites = [("frontend_checks", "Frontend Checks")]
    else:
        suites = [
            ("backend_imports", "Backend Imports & DuckDB"),
            ("backend_fastapi", "Backend FastAPI Endpoints"),
            ("api_contracts", "API Contract Validation"),
            ("solver_checks", "Solver End-to-End (Heuristic/LpOpt/Compare)"),
        ]
        if not args.quick:
            suites.append(("frontend_checks", "Frontend Checks"))
        suites.append(("integration", "Integration (Live Servers)"))

    for module_name, suite_name in suites:
        print_suite(suite_name)
        try:
            runner = load_suite(module_name)
            results = runner()
            all_results.extend(results)
            for r in results:
                print_result(r)
        except Exception as e:
            print(f"  {color('SUITE ERROR', RED)}: {e}")
            all_results.append({"name": f"suite:{module_name}", "passed": False, "detail": str(e)})

    elapsed = time.perf_counter() - start
    success = print_summary(all_results, elapsed)
    report_path = save_report(all_results, elapsed, args)

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
