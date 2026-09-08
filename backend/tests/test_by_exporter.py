from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import pandas as pd

from app.services.by_exporter import build_by_export_zip


def test_build_by_export_zip_patches_csv_and_delta_summary() -> None:
    baseline = {
        "sourcing": pd.DataFrame([
            {
                "ITEM": "ITEM1",
                "SOURCE": "SRC1",
                "DEST": "DEST1",
                "SOURCING": "ITEM1_SRC1_DEST1",
                "EFF": "01-01-1970",
                "DISC": "01-01-1970",
                "FACTOR": 1,
            }
        ])
    }
    archive = build_by_export_zip(
        baseline,
        [{"type": "sourcing", "key": "ITEM1|SRC1|DEST1", "value": 0.25}],
        timestamp=datetime(2026, 9, 4, 12, 34, 56),
    )

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert sorted(zf.namelist()) == ["delta_summary.json", "if_snop_sourcing-20260904123456.csv"]
        summary = json.loads(zf.read("delta_summary.json"))
        csv_lines = zf.read("if_snop_sourcing-20260904123456.csv").decode("utf-8").splitlines()

    assert summary["delta_count"] == 1
    assert csv_lines[0] == "ITEM|SOURCE|DEST|SOURCING|EFF|DISC|FACTOR"
    assert csv_lines[1] == "ITEM1|SRC1|DEST1|ITEM1_SRC1_DEST1|19700101000000|19700101000000|0.75"