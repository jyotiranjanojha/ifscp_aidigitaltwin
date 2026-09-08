from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.calendar_resolver import CalendarResolver, TimeBucket  # noqa: E402


DEFAULT_DATA_DIR = Path(
    r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658"
)
FILE_PATTERN = re.compile(r"^if_snop_([a-z]+)-20251013\d*\.csv$", re.IGNORECASE)


def test_calendar_resolver_real_data_pack_smoke() -> None:
    conn = _load_real_by_pack()
    resolver = CalendarResolver(conn)

    assert len(resolver.index) > 0
    assert resolver.get_time_phased_bom_yield(
        "100000000004",
        "SUBITEM",
        "IF_BOM_YCAL_100000000004_1004",
        datetime(2025, 7, 27),
    ) == 0.985
    assert resolver.get_time_phased_resource_capacity(
        "RES",
        "NO_SUCH_CAL",
        datetime(2025, 7, 27),
        datetime(2025, 7, 28),
    ) == 24.0

    params = resolver.generate_time_phased_model_parameters([
        TimeBucket("t0", datetime(2025, 7, 27), datetime(2025, 7, 28)),
        TimeBucket("t1", datetime(2025, 8, 3), datetime(2025, 8, 4)),
    ])
    assert params["CapMatrix"].shape[1] == 2
    assert params["YieldMatrix"].shape[1] == 2
    assert params["ValidShipDays"].shape[1] == 2


def _load_real_by_pack() -> duckdb.DuckDBPyConnection:
    data_dir = Path(os.environ.get("BY_DATA_DIR", DEFAULT_DATA_DIR))
    conn = duckdb.connect(":memory:")
    for csv_path in sorted(data_dir.glob("if_snop_*-20251013*.csv")):
        match = FILE_PATTERN.match(csv_path.name)
        if not match:
            continue
        entity = match.group(1).lower()
        df = _read_by_csv(csv_path)
        conn.register(f"{entity}_df", df)
        conn.execute(f'CREATE TABLE "{entity}" AS SELECT * FROM "{entity}_df"')
        conn.unregister(f"{entity}_df")
    return conn


def _read_by_csv(csv_path: Path) -> pd.DataFrame:
    content = csv_path.read_bytes()
    header = content.splitlines()[0].decode("utf-8-sig", errors="ignore") if content else ""
    delimiter = max(["|", ",", "\t", ";"], key=header.count)
    df = pd.read_csv(csv_path, sep=delimiter)
    df.columns = [str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper() for column in df.columns]
    return df