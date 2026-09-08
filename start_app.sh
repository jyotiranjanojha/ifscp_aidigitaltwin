#!/usr/bin/env bash
# Blue Yonder Supply Chain Digital Twin - macOS/Linux launcher.
# Delegates dependency setup, clean port restart, and Ctrl+C shutdown to run.py.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_ROOT}"

exec python3 run.py