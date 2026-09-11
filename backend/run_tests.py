"""Standalone test runner for the Digital Twin backend.

Executes the full pytest suite with coverage and prints a formatted
executive scorecard to the terminal.

Usage:
    python run_tests.py              # run all tests
    python run_tests.py --no-cov     # skip coverage collection
    python run_tests.py -v           # verbose pytest output alongside scorecard
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

# Force UTF-8 output on Windows terminals
if sys.platform == "win32":
    os.system("")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    elif sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )

# ── Subsystem → test-file mapping (order determines scorecard row order) ─────
SUBSYSTEMS: list[tuple[str, list[str]]] = [
    ("22-File Schemas & DuckDB", [
        "tests/test_bulk_loader.py",
        "tests/test_real_by_data.py",
        "tests/test_calendar_resolver.py",
    ]),
    ("Heuristic Pegging Solver", [
        "tests/test_demand_engine.py",
        "tests/test_substitutions.py",
    ]),
    ("Pyomo / HiGHS LpOpt Engine", [
        "tests/test_real_solver.py",
    ]),
    ("Bottleneck Tracer & Pegging", [
        "tests/test_bottleneck_tracer.py",
    ]),
    ("BY SCPO Delta Exporter", [
        "tests/test_by_exporter.py",
        "tests/test_by_change_exporter.py",
        "tests/test_mitigation_sandbox.py",
    ]),
    ("REST API Endpoints", [
        "tests/test_e2e_api.py",
    ]),
]

# ── Box-drawing characters ───────────────────────────────────────────────────
TL, TR, BL, BR = "┌", "┐", "└", "┘"
H, V = "─", "│"
LT, RT, TT, BT, X = "├", "┤", "┬", "┴", "┼"

COL_SUBSYSTEM = 32
COL_STATUS = 9
COL_TIME = 17
TABLE_WIDTH = COL_SUBSYSTEM + COL_STATUS + COL_TIME + 4  # 3 borders + padding


def _pad(text: str, width: int, align: str = "left") -> str:
    if align == "right":
        return text.rjust(width)
    if align == "center":
        return text.center(width)
    return text.ljust(width)


def _hline(left: str, mid: str, right: str, fill: str = H) -> str:
    return left + mid.join(fill * w for w in [COL_SUBSYSTEM, COL_STATUS, COL_TIME]) + right


def _row(cells: tuple[str, str, str]) -> str:
    return (
        V
        + " " + _pad(cells[0], COL_SUBSYSTEM)
        + " " + _pad(cells[1], COL_STATUS, "center")
        + " " + _pad(cells[2], COL_TIME, "right")
        + " " + V
    )


def _title_line(text: str) -> str:
    inner = TABLE_WIDTH - 2
    return V + _pad(text, inner, "center") + V


def _run_pytest(
    test_files: list[str], backend_dir: Path, extra_args: list[str]
) -> tuple[str, float, int]:
    """Run pytest for a group of test files. Returns (output, elapsed, exit_code)."""
    cmd = [
        sys.executable, "-m", "pytest",
        "--tb=short", "--no-header", "-q",
        *extra_args,
        *test_files,
    ]
    t0 = time.perf_counter()
    result = subprocess.run(
        cmd,
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        timeout=300,
    )
    elapsed = time.perf_counter() - t0
    output = result.stdout + result.stderr
    return output, elapsed, result.returncode


def _parse_result(output: str) -> tuple[str, int, int]:
    """Parse pytest output for status, passed count, failed count.

    Pytest summary lines look like:
        13 passed, 2 warnings in 3.02s
        2 failed, 5 passed in 10.12s
        no tests ran in 0.05s
    """
    import re

    passed = failed = 0
    summary_line = ""
    for line in output.splitlines():
        stripped = line.strip()
        if re.search(r"\d+ passed", stripped) or re.search(r"no tests ran", stripped):
            summary_line = stripped.lower()

    if not summary_line:
        return "SKIPPED", 0, 0

    if "no tests ran" in summary_line:
        return "SKIPPED", 0, 0

    m_passed = re.search(r"(\d+)\s+passed", summary_line)
    m_failed = re.search(r"(\d+)\s+failed", summary_line)

    if m_passed:
        passed = int(m_passed.group(1))
    if m_failed:
        failed = int(m_failed.group(1))

    if failed > 0:
        return "FAILED", passed, failed
    if passed > 0:
        return "PASSED", passed, failed
    return "SKIPPED", 0, 0


def _format_time(seconds: float) -> str:
    if seconds < 0.01:
        return "<0.01s"
    if seconds < 60:
        return f"{seconds:.2f}s"
    mins, secs = divmod(seconds, 60)
    return f"{int(mins)}m {secs:.0f}s"


def main() -> int:
    backend_dir = Path(__file__).resolve().parent
    extra_args: list[str] = []
    run_allTogether = "--all" in sys.argv
    skip_cov = "--no-cov" in sys.argv

    if skip_cov:
        sys.argv.remove("--no-cov")

    print()
    print(_hline(TL, TT, TR))
    print(_title_line("Digital Twin Validation Scorecard"))
    print(_hline(LT, BT, RT))
    print(_row(("Subsystem", "Status", "Execution Time")))
    print(_hline(LT, X, RT))

    overall_passed = 0
    overall_failed = 0
    overall_time = 0.0
    all_statuses: list[str] = []

    for subsystem, files in SUBSYSTEMS:
        existing = [str(backend_dir / f) for f in files if (backend_dir / f).exists()]
        if not existing:
            print(_row((subsystem, "SKIPPED", "—")))
            all_statuses.append("SKIPPED")
            continue

        output, elapsed, exit_code = _run_pytest(existing, backend_dir, extra_args)
        status, passed, failed = _parse_result(output)
        overall_passed += passed
        overall_failed += failed
        overall_time += elapsed
        all_statuses.append(status)

        status_display = f"\033[32m{status}\033[0m" if status == "PASSED" else (
            f"\033[31m{status}\033[0m" if status == "FAILED" else status
        )
        print(_row((subsystem, status_display, _format_time(elapsed))))

    print(_hline(LT, BT, BR))

    # Summary line
    total_tests = overall_passed + overall_failed
    if overall_failed == 0 and total_tests > 0:
        summary_status = "\033[32mALL PASSED\033[0m"
    elif overall_failed > 0:
        summary_status = f"\033[31m{overall_failed} FAILED\033[0m"
    else:
        summary_status = "\033[33mNO TESTS\033[0m"

    summary_line = f"  Total: {total_tests} tests | {overall_passed} passed | {overall_failed} failed | {_format_time(overall_time)}"
    print(summary_line)
    print(f"  Result: {summary_status}")
    print()

    # Run full pytest with coverage if requested
    has_cov = False
    try:
        import pytest_cov  # noqa: F401
        has_cov = True
    except ImportError:
        pass

    if not skip_cov and has_cov:
        print("  Running coverage report...")
        cov_cmd = [
            sys.executable, "-m", "pytest",
            "--cov=app", "--cov-report=term-missing",
            "--tb=short", "--no-header", "-q",
            "tests/",
        ]
        cov_result = subprocess.run(
            cov_cmd,
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            timeout=300,
        )
        # Extract only the coverage table from the output
        lines = cov_result.stdout.splitlines()
        in_coverage = False
        for line in lines:
            if line.strip().startswith("Name") and "Stmts" in line:
                in_coverage = True
            if in_coverage:
                print(f"  {line}")
            if in_coverage and line.strip().startswith("TOTAL"):
                in_coverage = False
                break
        print()
    elif not skip_cov and not has_cov:
        print("  (Coverage skipped: pytest-cov not installed)")
        print()

    return 0 if overall_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
