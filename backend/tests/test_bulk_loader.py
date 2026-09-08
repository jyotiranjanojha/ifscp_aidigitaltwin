from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.bulk_loader import get_data_summary  # noqa: E402


DEFAULT_DATA_DIR = Path(
    r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658"
)


def test_get_data_summary_real_pack_is_cached_and_has_topology() -> None:
    data_dir = Path(os.environ.get("BY_DATA_DIR", DEFAULT_DATA_DIR))
    summary = get_data_summary(data_dir)
    cached_summary = get_data_summary(data_dir)

    assert summary["table_count"] == 22
    assert summary["row_counts"]["sourcing"] == 58
    assert summary["topology"]["nodes"] == 9
    assert summary["topology"]["sourcing_lanes"] == 58
    assert summary["topology"]["active_skus"] == 51
    assert cached_summary == summary