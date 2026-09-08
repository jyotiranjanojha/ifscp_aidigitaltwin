#!/usr/bin/env python3
"""
Stop all sp_digitaltwin services (backend on 8000, frontend on 3000) safely.

Usage:
    python stop_app.py          # silent stop, logs to logs/app.log
    python stop_app.py --status # check if services are running
"""

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from logger_config import get_logger, _LOG_FORMAT, _DATE_FORMAT

logger = get_logger("run")

BACKEND_PORT = 8000
FRONTEND_PORT = 3000
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _setup_file_log():
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "stop.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    logging.getLogger("run").addHandler(fh)


def _find_pids_on_port(port: int) -> list[int]:
    pids = []
    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            creationflags=_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            # Extract port precisely using boundary check to avoid substring overlap
            if "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    local_addr = parts[1]
                    addr_port = local_addr.rsplit(':', 1)[-1]
                    if addr_port == str(port):
                        try:
                            pids.append(int(parts[-1]))
                        except ValueError:
                            pass
    else:
        if shutil.which("lsof"):
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"], capture_output=True, text=True,
                )
                for pid_str in result.stdout.strip().split():
                    try:
                        pids.append(int(pid_str))
                    except ValueError:
                        pass
            except Exception as e:
                logger.warning("Error running lsof for port %d: %s", port, e)
        else:
            logger.warning("lsof utility not found in PATH. Skipping active process check.")
            
    return sorted(list(set(pids)))  # Deduplicate PIDs


def stop_services():
    _setup_file_log()
    stopped = 0
    for port in [BACKEND_PORT, FRONTEND_PORT]:
        pids = _find_pids_on_port(port)
        for pid in pids:
            logger.info("Stopping PID %d on port %d", pid, port)
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        creationflags=_NO_WINDOW,
                        capture_output=True,
                    )
                else:
                    # Safe Direct Targeting: Kill only the listener, avoiding parent terminal disruption
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(0.5)
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                stopped += 1
            except Exception as e:
                logger.warning("Failed to stop PID %d: %s", pid, e)

    if stopped:
        logger.info("Stopped %d process(es).", stopped)
    else:
        logger.info("No running services found on ports %d/%d.", BACKEND_PORT, FRONTEND_PORT)
    return stopped


def check_status():
    _setup_file_log()
    status = {}
    for port, name in [(BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend")]:
        pids = _find_pids_on_port(port)
        status[name] = {"port": port, "running": len(pids) > 0, "pids": pids}
        state = "RUNNING" if pids else "STOPPED"
        logger.info("%s (port %d): %s (PIDs: %s)", name, port, state, pids or "none")
    return status


if __name__ == "__main__":
    if "--status" in sys.argv:
        check_status()
    else:
        stop_services()
