"""Shared configuration for the smoke test suite."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

BACKEND_VENV_PYTHON = BACKEND_DIR / "venv" / "Scripts" / "python.exe"
BACKEND_PYTHON = BACKEND_VENV_PYTHON if BACKEND_VENV_PYTHON.exists() else Path("python")

FRONTEND_NODE_MODULES = FRONTEND_DIR / "node_modules"
FRONTEND_PACKAGE_JSON = FRONTEND_DIR / "package.json"

BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))

BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
FRONTEND_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}" if "FRONTEND_HOST" in os else f"http://127.0.0.1:{FRONTEND_PORT}"

TIMEOUT_SHORT = 10
TIMEOUT_MEDIUM = 30
TIMEOUT_LONG = 60
