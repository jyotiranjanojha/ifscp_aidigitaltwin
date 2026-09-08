#!/usr/bin/env python3
"""
Cross-platform launcher for Blue Yonder Supply Chain Digital Twin.

Performs automated dependency checks and launches both FastAPI backend
and Next.js frontend in parallel with proper process management.

All operations are logged to logs/app.log and logs/run.log.
"""

import logging
import os
import re
import sys
import subprocess
import time
import signal
import shutil
import urllib.request
from pathlib import Path
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from logger_config import get_logger, _LOG_FORMAT, _DATE_FORMAT

logger = get_logger("run")


BACKEND_PORT = 8000
FRONTEND_PORT = 3000
BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ProcessManager:
    def __init__(self):
        self.processes: List[Tuple[subprocess.Popen, str]] = []
        self.running = True

    def add(self, proc: subprocess.Popen, name: str):
        self.processes.append((proc, name))

    def terminate_all(self):
        self.running = False
        for proc, name in self.processes:
            if proc.poll() is None:
                logger.info("Terminating %s (PID: %d)...", name, proc.pid)
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            creationflags=_NO_WINDOW,
                            capture_output=True,
                        )
                    else:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                        except Exception:
                            os.kill(proc.pid, signal.SIGTERM)
                except Exception as e:
                    logger.warning("Failed to terminate %s: %s", name, e)

        for proc, name in self.processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing %s...", name)
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            creationflags=_NO_WINDOW,
                            capture_output=True,
                        )
                    else:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except Exception:
                            os.kill(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
                proc.wait()

        logger.info("All services stopped.")


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent


def run_command(cmd: List[str], cwd: Path, description: str) -> bool:
    logger.info("%s ...", description)
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=300,
            creationflags=_NO_WINDOW, shell=(sys.platform == "win32"),
        )
        if result.returncode != 0:
            logger.error("%s failed: %s", description, result.stderr.strip())
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after 5 minutes", description)
        return False
    except Exception as e:
        logger.error("%s error: %s", description, e)
        return False


def setup_backend(project_root: Path) -> Optional[Path]:
    backend_dir = project_root / "backend"
    venv_dir = backend_dir / "venv"

    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
        venv_pip = venv_dir / "Scripts" / "pip.exe"
        venv_uvicorn = venv_dir / "Scripts" / "uvicorn.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
        venv_pip = venv_dir / "bin" / "pip"
        venv_uvicorn = venv_dir / "bin" / "uvicorn"

    # Integrity verification: Recreate venv if incomplete/corrupt
    if not venv_dir.exists() or not venv_python.exists() or not venv_pip.exists():
        logger.info("Creating backend virtual environment...")
        if venv_dir.exists():
            logger.warning("Virtual environment directory exists but is corrupt or incomplete. Recreating...")
            shutil.rmtree(venv_dir, ignore_errors=True)
            
        if not run_command([sys.executable, "-m", "venv", str(venv_dir)], project_root, "Create venv"):
            return None
    else:
        logger.info("Backend virtual environment exists and is healthy.")

    if not run_command([str(venv_pip), "install", "--upgrade", "pip"], backend_dir, "Upgrade pip"):
        logger.warning("pip upgrade skipped (non-critical)")

    req_file = backend_dir / "requirements.txt"
    if not req_file.exists():
        logger.error("requirements.txt not found at %s", req_file)
        return None

    if not run_command([str(venv_pip), "install", "-r", str(req_file)], backend_dir, "Install Python deps"):
        return None

    logger.info("Backend dependencies ready.")
    return venv_uvicorn


def check_node_compatibility() -> bool:
    """Verifies that Node.js is installed and meets the minimum version requirement (>= 18.17.0)."""
    if not shutil.which("node"):
        logger.error("Node.js is not found in PATH. Please install Node.js (v18.17.0 or higher).")
        return False

    try:
        result = subprocess.run(["node", "-v"], capture_output=True, text=True, check=True)
        version_str = result.stdout.strip()
        
        match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", version_str)
        if match:
            major, minor, patch = map(int, match.groups())
            if (major < 18) or (major == 18 and minor < 17):
                logger.error(
                    "Compatible Node.js version not found. Required: >= v18.17.0. Found: %s", 
                    version_str
                )
                return False
            
            logger.info("Node.js version compatible: %s", version_str)
            return True
        else:
            logger.warning("Could not parse Node.js version '%s'. Continuing...", version_str)
            return True
            
    except Exception as e:
        logger.warning("Failed to determine Node.js version: %s. Continuing with caution.", e)
        return True


def setup_frontend(project_root: Path) -> bool:
    """Performs automated validation and dependency preparation for the frontend."""
    frontend_dir = project_root / "frontend"
    package_json = frontend_dir / "package.json"

    # 1. Directory Integrity Checks
    if not frontend_dir.exists() or not package_json.exists():
        logger.error("Frontend folder is missing or incomplete. package.json not found at: %s", package_json)
        return False

    # 2. Compatibility Checks
    if not check_node_compatibility():
        return False

    if not shutil.which("npm"):
        logger.error("npm not found in PATH. Please install Node.js.")
        return False

    # 3. Dependencies Install
    if not run_command(["npm", "install", "--legacy-peer-deps"], frontend_dir, "Install/update frontend deps"):
        return False
        
    logger.info("Frontend dependencies ready.")
    return True


def launch_backend(uvicorn_path: Path, project_root: Path, pm: ProcessManager) -> bool:
    backend_dir = project_root / "backend"
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    backend_log = log_dir / "backend.log"

    logger.info("Starting FastAPI backend on %s -> %s", BACKEND_URL, backend_log)

    try:
        log_fh = open(backend_log, "w", encoding="utf-8")
        if sys.platform == "win32":
            proc = subprocess.Popen(
                [str(uvicorn_path), "main:app", "--reload", "--port", str(BACKEND_PORT)],
                cwd=backend_dir,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WINDOW,
            )
        else:
            proc = subprocess.Popen(
                [str(uvicorn_path), "main:app", "--reload", "--port", str(BACKEND_PORT)],
                cwd=backend_dir,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pm.add(proc, "FastAPI Backend")
        logger.info("Backend started (PID: %d)", proc.pid)
        return True
    except Exception as e:
        logger.error("Failed to start backend: %s", e)
        return False


def launch_frontend(project_root: Path, pm: ProcessManager) -> bool:
    frontend_dir = project_root / "frontend"
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    frontend_log = log_dir / "frontend.log"

    logger.info("Starting Next.js frontend on %s -> %s", FRONTEND_URL, frontend_log)

    env = os.environ.copy()
    env["NEXT_PUBLIC_API_BASE"] = BACKEND_URL

    try:
        log_fh = open(frontend_log, "w", encoding="utf-8")
        if sys.platform == "win32":
            proc = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=frontend_dir,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WINDOW,
                shell=True,
                env=env,
            )
        else:
            proc = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=frontend_dir,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
        pm.add(proc, "Next.js Frontend")
        logger.info("Frontend started (PID: %d)", proc.pid)
        return True
    except Exception as e:
        logger.error("Failed to start frontend: %s", e)
        return False


def clear_cache(project_root: Path):
    backend_dir = project_root / "backend"
    count = 0
    for pycache in backend_dir.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache)
            count += 1
        except Exception:
            pass
    for pyc in backend_dir.rglob("*.pyc"):
        try:
            pyc.unlink()
            count += 1
        except Exception:
            pass
    if count:
        logger.info("Cache cleared (%d items).", count)


def kill_existing_processes():
    if sys.platform == "win32":
        for port in [BACKEND_PORT, FRONTEND_PORT]:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                creationflags=_NO_WINDOW,
            )
            killed = 0
            for line in result.stdout.splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        local_addr = parts[1]
                        addr_port = local_addr.rsplit(':', 1)[-1]
                        if addr_port == str(port):
                            pid = parts[-1]
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", pid],
                                creationflags=_NO_WINDOW,
                                capture_output=True,
                            )
                            killed += 1
            if killed:
                logger.info("Killed %d process(es) on port %d.", killed, port)
    else:
        for port in [BACKEND_PORT, FRONTEND_PORT]:
            if shutil.which("lsof"):
                try:
                    result = subprocess.run(
                        ["lsof", "-ti", f":{port}"], capture_output=True, text=True,
                    )
                    for pid_str in result.stdout.strip().split():
                        try:
                            pid = int(pid_str)
                            os.kill(pid, signal.SIGKILL)
                            logger.info("Killed PID %d on port %d.", pid, port)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("Failed checking port %d during process cleanup: %s", port, e)
            else:
                logger.warning("lsof utility not found. Skipping active port-cleanup.")


def wait_for_url(url: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def main():
    project_root = _find_project_root()
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)

    # CRITICAL: Validate environments BEFORE running destructive cleanups or logs creation
    if sys.version_info < (3, 11):
        logger.error("Python 3.11+ is required. Current: %s. Aborting startup.", sys.version.split()[0])
        return 1

    run_log_fh = logging.FileHandler(log_dir / "run.log", encoding="utf-8")
    run_log_fh.setLevel(logging.DEBUG)
    run_log_fh.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    logging.getLogger("run").addHandler(run_log_fh)

    logger.info("=" * 60)
    logger.info("sp_digitaltwin launcher starting")
    logger.info("Python %s | Platform: %s", sys.version.split()[0], sys.platform)
    logger.info("Project root: %s", project_root)
    logger.info("=" * 60)

    logger.info("Cleaning up existing processes...")
    kill_existing_processes()
    clear_cache(project_root)

    venv_uvicorn = setup_backend(project_root)
    if not venv_uvicorn:
        return 1

    if not setup_frontend(project_root):
        return 1

    logger.info("Backend: %s | Frontend: %s | Docs: %s/docs", BACKEND_URL, FRONTEND_URL, BACKEND_URL)

    pm = ProcessManager()

    if not launch_backend(venv_uvicorn, project_root, pm):
        return 1

    logger.info("Waiting for backend to be ready...")
    if not wait_for_url(f"{BACKEND_URL}/"):
        logger.error("Backend did not become ready in time.")
        pm.terminate_all()
        return 1
    logger.info("Backend is ready.")

    if not launch_frontend(project_root, pm):
        pm.terminate_all()
        return 1

    logger.info("Waiting for frontend to be ready...")
    if not wait_for_url(FRONTEND_URL):
        logger.error("Frontend did not become ready in time.")
        pm.terminate_all()
        return 1
    logger.info("Frontend is ready.")

    logger.info("All services running. Press Ctrl+C to stop.")

    def signal_handler(signum, frame):
        logger.info("Shutdown signal received (signal=%d).", signum)
        pm.terminate_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    try:
        while pm.running and any(p.poll() is None for p, _ in pm.processes):
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received.")
    finally:
        pm.terminate_all()

    return 0


if __name__ == "__main__":
    sys.exit(main())
