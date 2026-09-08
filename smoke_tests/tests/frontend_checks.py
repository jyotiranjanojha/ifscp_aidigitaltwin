"""Frontend smoke tests: TypeScript, build, component imports, CSS."""

import json
import re
import subprocess
import time
from pathlib import Path

RESULTS: list[dict] = []
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

def record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0):
    RESULTS.append({"name": name, "passed": passed, "detail": detail, "elapsed_ms": elapsed_ms})

def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    import platform
    use_shell = platform.system() == "Windows"
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, shell=use_shell)
    return proc.returncode, proc.stdout, proc.stderr

def test_typescript_check():
    t0 = time.perf_counter()
    try:
        rc, stdout, stderr = _run(["npx", "tsc", "--noEmit"], FRONTEND_DIR, timeout=120)
        elapsed = (time.perf_counter() - t0) * 1000
        if rc == 0:
            record("tsc:no_errors", True, "Clean compilation", elapsed)
        else:
            errors = [l for l in stderr.strip().split("\n") if l.strip()][:5]
            record("tsc:no_errors", False, f"{len(errors)} errors: " + "; ".join(errors), elapsed)
    except subprocess.TimeoutExpired:
        record("tsc:no_errors", False, "tsc timed out after 120s", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("tsc:no_errors", False, str(e), (time.perf_counter() - t0) * 1000)

def test_next_build():
    t0 = time.perf_counter()
    try:
        rc, stdout, stderr = _run(["npx", "next", "build"], FRONTEND_DIR, timeout=300)
        elapsed = (time.perf_counter() - t0) * 1000
        output = stdout + stderr
        if rc == 0 and "compiled" in output.lower():
            record("next:build", True, "Build succeeded", elapsed)
        else:
            last_lines = [l for l in output.strip().split("\n") if l.strip()][-5:]
            record("next:build", False, "Build failed: " + " | ".join(last_lines), elapsed)
    except subprocess.TimeoutExpired:
        record("next:build", False, "Build timed out after 300s", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("next:build", False, str(e), (time.perf_counter() - t0) * 1000)

def test_package_json_valid():
    t0 = time.perf_counter()
    try:
        pkg_path = FRONTEND_DIR / "package.json"
        assert pkg_path.exists(), "package.json not found"
        with open(pkg_path) as f:
            pkg = json.load(f)
        assert "dependencies" in pkg, "Missing dependencies"
        assert "next" in pkg["dependencies"], "Missing next dependency"
        assert "react" in pkg["dependencies"], "Missing react dependency"
        scripts = pkg.get("scripts", {})
        assert "dev" in scripts, "Missing dev script"
        assert "build" in scripts, "Missing build script"
        record("frontend:package_json", True, f"next={pkg['dependencies']['next']}", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("frontend:package_json", False, str(e), (time.perf_counter() - t0) * 1000)

def test_component_files_exist():
    t0 = time.perf_counter()
    expected = [
        "app/page.tsx",
        "app/layout.tsx",
        "app/globals.css",
        "src/components/PlannerCockpit.tsx",
        "src/components/SolverSelector.tsx",
        "src/components/DualSolverComparator.tsx",
        "src/components/visualization/SupplyChainGraphTwin.tsx",
        "src/components/visualization/GeoSpatialFlowTwin.tsx",
        "src/components/visualization/GeoSpatialFlowTwinLoader.tsx",
        "src/services/simulationApi.ts",
    ]
    missing = [f for f in expected if not (FRONTEND_DIR / f).exists()]
    elapsed = (time.perf_counter() - t0) * 1000
    if not missing:
        record("frontend:component_files", True, f"{len(expected)} files present", elapsed)
    else:
        record("frontend:component_files", False, f"Missing: {', '.join(missing)}", elapsed)

def test_imports_resolve():
    t0 = time.perf_counter()
    try:
        pkg_path = FRONTEND_DIR / "package.json"
        with open(pkg_path) as f:
            pkg = json.load(f)
        deps = list(pkg.get("dependencies", {}).keys())
        missing = [d for d in deps if not (FRONTEND_DIR / "node_modules" / d).exists()]
        elapsed = (time.perf_counter() - t0) * 1000
        if not missing:
            record("frontend:node_modules", True, f"{len(deps)} deps installed", elapsed)
        else:
            record("frontend:node_modules", False, f"Missing: {', '.join(missing[:10])}", elapsed)
    except Exception as e:
        record("frontend:node_modules", False, str(e), (time.perf_counter() - t0) * 1000)

def test_css_import_order():
    t0 = time.perf_counter()
    try:
        css_path = FRONTEND_DIR / "app" / "globals.css"
        assert css_path.exists(), "globals.css not found"
        content = css_path.read_text(encoding="utf-8")
        import_pos = content.find("@import")
        tailwind_pos = content.find("@tailwind")
        if import_pos == -1:
            record("frontend:css_import_order", True, "No @import found (ok)", (time.perf_counter() - t0) * 1000)
        elif tailwind_pos == -1:
            record("frontend:css_import_order", False, "@tailwind not found", (time.perf_counter() - t0) * 1000)
        elif import_pos < tailwind_pos:
            record("frontend:css_import_order", True, "@import before @tailwind", (time.perf_counter() - t0) * 1000)
        else:
            record("frontend:css_import_order", False, f"@import at pos {import_pos}, @tailwind at {tailwind_pos} — wrong order", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("frontend:css_import_order", False, str(e), (time.perf_counter() - t0) * 1000)

def test_tsconfig_valid():
    t0 = time.perf_counter()
    try:
        ts_path = FRONTEND_DIR / "tsconfig.json"
        assert ts_path.exists(), "tsconfig.json not found"
        with open(ts_path) as f:
            content = f.read()
        tsconfig = json.loads(content)
        compiler = tsconfig.get("compilerOptions", {})
        assert "paths" in compiler, "Missing paths"
        assert "@/*" in compiler["paths"], "Missing @/* alias"
        record("frontend:tsconfig", True, f"alias=@/*", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("frontend:tsconfig", False, str(e), (time.perf_counter() - t0) * 1000)

def test_env_local_exists():
    t0 = time.perf_counter()
    try:
        env_path = FRONTEND_DIR / ".env.local"
        assert env_path.exists(), ".env.local not found"
        content = env_path.read_text(encoding="utf-8")
        has_api = "NEXT_PUBLIC_API_BASE" in content
        has_maplibre = "NEXT_PUBLIC_MAPLIBRE_STYLE_URL" in content
        record("frontend:env_local", True, f"api={has_api} maplibre={has_maplibre}", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        record("frontend:env_local", False, str(e), (time.perf_counter() - t0) * 1000)

def run_all() -> list[dict]:
    test_package_json_valid()
    test_component_files_exist()
    test_imports_resolve()
    test_css_import_order()
    test_tsconfig_valid()
    test_env_local_exists()
    test_typescript_check()
    test_next_build()
    return RESULTS
