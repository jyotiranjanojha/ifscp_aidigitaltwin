from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import duckdb

from schema_config import PRIMARY_KEY_COLUMNS_BY_ENTITY


DEFAULT_DATA_DIR = Path(
    r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658"
)
FILE_PATTERN = re.compile(r"^if_snop_([a-z]+)-\d{14}\.csv$", re.IGNORECASE)


@dataclass(frozen=True)
class BulkLoadResult:
    conn: duckdb.DuckDBPyConnection
    data_dir: Path
    row_counts: dict[str, int]
    load_time_seconds: float


_SUMMARY_CACHE: dict[tuple[str, float], dict[str, Any]] = {}


def resolve_data_dir(data_dir: Optional[str | Path] = None) -> Path:
    path = Path(data_dir or os.environ.get("BY_DATA_DIR", DEFAULT_DATA_DIR))
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"BY data directory does not exist: {path}")
    return path


def load_by_csv_pack(data_dir: Optional[str | Path] = None) -> BulkLoadResult:
    path = resolve_data_dir(data_dir)
    start = time.perf_counter()
    conn = duckdb.connect(":memory:")
    row_counts: dict[str, int] = {}

    for csv_path in sorted(path.glob("if_snop_*-*.csv")):
        match = FILE_PATTERN.match(csv_path.name)
        if not match:
            continue
        entity = match.group(1).lower()
        conn.execute(
            f'''
            CREATE TABLE "{entity}" AS
            SELECT * FROM read_csv_auto(?, delim='|', header=true, normalize_names=false, ignore_errors=true)
            ''',
            [str(csv_path)],
        )
        _normalize_table_columns(conn, entity)
        row_counts[entity] = conn.execute(f'SELECT COUNT(*) FROM "{entity}"').fetchone()[0]
        _create_primary_key_index(conn, entity)

    return BulkLoadResult(conn=conn, data_dir=path, row_counts=row_counts, load_time_seconds=time.perf_counter() - start)


def get_data_summary(data_dir: Optional[str | Path] = None) -> dict[str, Any]:
    path = resolve_data_dir(data_dir)
    cache_key = (str(path.resolve()), _folder_signature(path))
    if cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key]

    load_result = load_by_csv_pack(path)
    summary = build_data_summary(load_result)
    _SUMMARY_CACHE.clear()
    _SUMMARY_CACHE[cache_key] = summary
    return summary


def build_data_summary(load_result: BulkLoadResult) -> dict[str, Any]:
    conn = load_result.conn
    network_nodes = _distinct_count(conn, "SELECT SOURCE AS node FROM network UNION SELECT DEST AS node FROM network")
    sourcing_lanes = _count_rows(conn, "sourcing")
    active_skus = _distinct_count(conn, "SELECT ITEM || '|' || LOC AS node FROM sku WHERE COALESCE(ENABLEOPT, 1) <> 0")
    memory_bytes = _estimate_memory_bytes(conn, load_result.row_counts)
    return {
        "data_dir": str(load_result.data_dir),
        "table_count": len(load_result.row_counts),
        "row_counts": load_result.row_counts,
        "load_time_seconds": round(load_result.load_time_seconds, 6),
        "memory_footprint_bytes": memory_bytes,
        "memory_footprint_mb": round(memory_bytes / (1024 * 1024), 3),
        "topology": {
            "nodes": network_nodes,
            "sourcing_lanes": sourcing_lanes,
            "active_skus": active_skus,
        },
    }


def _normalize_table_columns(conn: duckdb.DuckDBPyConnection, entity: str) -> None:
    columns = conn.execute(f'DESCRIBE "{entity}"').fetchall()
    for row in columns:
        original = row[0]
        normalized = _normalize_column_name(original)
        if normalized != original:
            conn.execute(f'ALTER TABLE "{entity}" RENAME COLUMN "{original}" TO "{normalized}"')


def _create_primary_key_index(conn: duckdb.DuckDBPyConnection, entity: str) -> None:
    columns = [column for column in sorted(PRIMARY_KEY_COLUMNS_BY_ENTITY.get(entity, set())) if _column_exists(conn, entity, column)]
    if columns:
        index_name = f"idx_{entity}_{'_'.join(columns).lower()}"
        column_sql = ", ".join(f'"{column}"' for column in columns)
        conn.execute(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{entity}" ({column_sql})')

    for columns in (("ITEM", "LOC"), ("SOURCE", "DEST", "ITEM"), ("RES", "LOC")):
        if all(_column_exists(conn, entity, column) for column in columns):
            index_name = f"idx_{entity}_{'_'.join(columns).lower()}"
            column_sql = ", ".join(f'"{column}"' for column in columns)
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{entity}" ({column_sql})')


def _column_exists(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    return bool(conn.execute(f'DESCRIBE "{table}"').fetchdf()["column_name"].eq(column).any())


def _count_rows(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _distinct_count(conn: duckdb.DuckDBPyConnection, query: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(DISTINCT node) FROM ({query}) q WHERE node IS NOT NULL").fetchone()[0])
    except duckdb.Error:
        return 0


def _table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE lower(table_name) = ?", [table.lower()]).fetchone()[0])


def _estimate_memory_bytes(conn: duckdb.DuckDBPyConnection, row_counts: dict[str, int]) -> int:
    total = 0
    for entity, row_count in row_counts.items():
        column_count = len(conn.execute(f'DESCRIBE "{entity}"').fetchall())
        total += row_count * max(column_count, 1) * 16
    return total


def _folder_signature(path: Path) -> float:
    return max((file.stat().st_mtime for file in path.glob("if_snop_*-*.csv")), default=0.0)


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()