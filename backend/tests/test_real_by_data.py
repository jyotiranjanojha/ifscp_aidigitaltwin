from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import ENTITY_SCHEMA_MAP, BYBaseModel  # noqa: E402
from schema_config import PRIMARY_KEY_COLUMNS_BY_ENTITY  # noqa: E402


DEFAULT_DATA_DIR = Path(
    r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\PythonScript\r3_rev10_131020251658"
)
FILE_PATTERN = re.compile(r"^if_snop_([a-z]+)-20251013\d*\.csv$", re.IGNORECASE)

@dataclass
class FileAuditResult:
    file_name: str
    entity: str
    row_count: int
    schema_status: str
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    null_pk_columns: dict[str, int] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.schema_status == "PASSED" and not self.null_pk_columns


@dataclass
class ReferentialIssue:
    check_name: str
    issue_count: int
    sample_values: list[Any]

    @property
    def passed(self) -> bool:
        return self.issue_count == 0


def test_real_blue_yonder_input_data_is_solver_ready(capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = _resolve_data_dir()
    files = _discover_files(data_dir)
    file_results: list[FileAuditResult] = []
    tables: dict[str, pd.DataFrame] = {}

    for entity, csv_path in files.items():
        df = _read_by_csv(csv_path)
        tables[entity] = df
        file_results.append(_audit_file(entity, csv_path, df))

    conn = _load_duckdb_tables(tables)
    referential_results = _audit_referential_integrity(conn, tables)
    report = _format_health_report(data_dir, file_results, referential_results)
    failed_files = [result for result in file_results if not result.passed]
    failed_refs = [result for result in referential_results if not result.passed]
    with capsys.disabled():
        print(report)

    assert not _missing_expected_entities(files), "Missing expected BY entity files. See health report above."
    assert not failed_files, "Schema or primary-key audit failed. See health report above."
    assert not failed_refs, "Referential integrity audit failed. See health report above."


def _resolve_data_dir() -> Path:
    configured = os.environ.get("BY_DATA_DIR")
    data_dir = Path(configured) if configured else DEFAULT_DATA_DIR
    if not data_dir.exists():
        pytest.fail(f"BY data directory does not exist: {data_dir}")
    if not data_dir.is_dir():
        pytest.fail(f"BY data path is not a directory: {data_dir}")
    return data_dir


def _discover_files(data_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for csv_path in sorted(data_dir.glob("if_snop_*-20251013*.csv")):
        match = FILE_PATTERN.match(csv_path.name)
        if not match:
            continue
        entity = match.group(1).lower()
        if entity in ENTITY_SCHEMA_MAP:
            files[entity] = csv_path
    if not files:
        pytest.fail(f"No BY files matching if_snop_*-20251013*.csv found in {data_dir}")
    return files


def _read_by_csv(csv_path: Path) -> pd.DataFrame:
    content = csv_path.read_bytes()
    header = content.splitlines()[0].decode("utf-8-sig", errors="ignore") if content else ""
    delimiter = max(["|", ",", "\t", ";"], key=header.count)
    df = pd.read_csv(csv_path, sep=delimiter)
    df.columns = [_normalize_column_name(column) for column in df.columns]
    return df


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


def _audit_file(entity: str, csv_path: Path, df: pd.DataFrame) -> FileAuditResult:
    schema_class = ENTITY_SCHEMA_MAP[entity]
    required_columns = set(getattr(schema_class, "_required_columns", set()))
    expected_columns = _expected_schema_columns(schema_class)
    received_columns = set(df.columns)
    missing_columns = sorted(required_columns - received_columns)
    extra_columns = sorted(received_columns - expected_columns)
    null_pk_columns = _null_primary_key_counts(entity, df)
    validation_errors = _validate_rows(schema_class, df)
    schema_status = "FAILED" if missing_columns or validation_errors else "PASSED"
    return FileAuditResult(
        file_name=csv_path.name,
        entity=entity,
        row_count=len(df),
        schema_status=schema_status,
        missing_columns=missing_columns,
        extra_columns=extra_columns,
        null_pk_columns=null_pk_columns,
        validation_errors=validation_errors,
    )


def _null_primary_key_counts(entity: str, df: pd.DataFrame) -> dict[str, int]:
    counts = {}
    for column in sorted(PRIMARY_KEY_COLUMNS_BY_ENTITY.get(entity, set())):
        if column not in df.columns:
            continue
        null_count = int(df[column].isna().sum() + (df[column].astype(str).str.strip() == "").sum())
        if null_count:
            counts[column] = null_count
    return counts


def _validate_rows(schema_class: type[BYBaseModel], df: pd.DataFrame) -> list[str]:
    errors = []
    for row_number, record in enumerate(df.to_dict(orient="records"), start=2):
        try:
            schema_class(**record)
        except ValidationError as exc:
            for error in exc.errors()[:5]:
                loc = ".".join(str(part) for part in error.get("loc", []))
                errors.append(f"row {row_number}: {loc}: {error.get('msg')}")
            if len(errors) >= 10:
                errors.append("additional row validation errors suppressed")
                break
    return errors


def _expected_schema_columns(schema_class: type[BYBaseModel]) -> set[str]:
    expected = set(schema_class.model_fields.keys())
    for field in schema_class.model_fields.values():
        if field.alias:
            expected.add(str(field.alias))
    return expected


def _load_duckdb_tables(tables: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    for entity, df in tables.items():
        conn.register(f"{entity}_df", df)
        conn.execute(f'CREATE TABLE "{entity}" AS SELECT * FROM "{entity}_df"')
        conn.unregister(f"{entity}_df")
    return conn


def _audit_referential_integrity(
    conn: duckdb.DuckDBPyConnection,
    tables: dict[str, pd.DataFrame],
) -> list[ReferentialIssue]:
    checks: list[ReferentialIssue] = []
    checks.append(_missing_entity_values(conn, tables, "sourcing", "ITEM", "items", "ITEM", "sourcing ITEMs missing in items"))
    checks.append(_missing_entity_values(conn, tables, "sourcing", "ITEM", "sku", "ITEM", "sourcing ITEMs missing in sku"))
    checks.append(_missing_entity_values(conn, tables, "network", "SOURCE", "locations", "LOC", "network SOURCEs missing in locations"))
    checks.append(_missing_entity_values(conn, tables, "network", "DEST", "locations", "LOC", "network DESTs missing in locations"))
    checks.append(_missing_entity_values(conn, tables, "sourcing", "SOURCE", "locations", "LOC", "sourcing SOURCEs missing in locations"))
    checks.append(_missing_entity_values(conn, tables, "sourcing", "DEST", "locations", "LOC", "sourcing DESTs missing in locations"))
    checks.append(_missing_entity_values(conn, tables, "productionstep", "RESOURCE|RES", "res", "RESOURCE|RES", "productionstep RES missing in res"))
    return checks


def _missing_entity_values(
    conn: duckdb.DuckDBPyConnection,
    tables: dict[str, pd.DataFrame],
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
    check_name: str,
) -> ReferentialIssue:
    if source_table not in tables or target_table not in tables:
        return ReferentialIssue(check_name, 0, ["SKIPPED: table missing"])

    resolved_source_column = _resolve_column(tables[source_table], source_column)
    resolved_target_column = _resolve_column(tables[target_table], target_column)
    if resolved_source_column is None or resolved_target_column is None:
        return ReferentialIssue(check_name, 0, ["SKIPPED: column missing"])

    rows = conn.execute(
        f'''
        SELECT DISTINCT CAST(s."{resolved_source_column}" AS VARCHAR) AS missing_value
        FROM "{source_table}" s
        LEFT JOIN "{target_table}" t
          ON CAST(s."{resolved_source_column}" AS VARCHAR) = CAST(t."{resolved_target_column}" AS VARCHAR)
        WHERE s."{resolved_source_column}" IS NOT NULL
          AND trim(CAST(s."{resolved_source_column}" AS VARCHAR)) <> ''
          AND t."{resolved_target_column}" IS NULL
        ORDER BY missing_value
        ''',
    ).fetchall()
    values = [row[0] for row in rows]
    return ReferentialIssue(check_name, len(values), values[:10])


def _resolve_column(df: pd.DataFrame, column_spec: str) -> str | None:
    for column in column_spec.split("|"):
        if column in df.columns:
            return column
    return None


def _format_health_report(
    data_dir: Path,
    file_results: list[FileAuditResult],
    referential_results: list[ReferentialIssue],
) -> str:
    lines = [
        "",
        "Blue Yonder Real-Data Health Report",
        f"Data directory: {data_dir}",
        "",
        "Schema Audit",
        _format_table(
            ["File Name", "Rows", "Schema", "Missing Columns", "Extra Columns", "Null PKs"],
            [
                [
                    result.file_name,
                    str(result.row_count),
                    result.schema_status,
                    ", ".join(result.missing_columns) or "-",
                    ", ".join(result.extra_columns) or "-",
                    ", ".join(f"{column}={count}" for column, count in result.null_pk_columns.items()) or "-",
                ]
                for result in sorted(file_results, key=lambda item: item.entity)
            ],
        ),
        "",
    ]

    validation_detail = [result for result in file_results if result.validation_errors]
    if validation_detail:
        lines.append("Schema Validation Details")
        for result in validation_detail:
            lines.append(f"- {result.file_name}")
            lines.extend(f"  * {error}" for error in result.validation_errors)
        lines.append("")

    missing_entities = _missing_expected_entities({result.entity: Path(result.file_name) for result in file_results})
    if missing_entities:
        lines.append(f"Missing expected entity files: {', '.join(missing_entities)}")
        lines.append("")

    lines.extend([
        "Referential Integrity Audit",
        _format_table(
            ["Check", "Status", "Issue Count", "Sample Values"],
            [
                [
                    result.check_name,
                    "PASSED" if result.passed else "FAILED",
                    str(result.issue_count),
                    ", ".join(str(value) for value in result.sample_values) or "-",
                ]
                for result in referential_results
            ],
        ),
        "",
        "Overall Status: " + ("PASSED" if all(r.passed for r in file_results) and all(r.passed for r in referential_results) and not missing_entities else "FAILED"),
    ])
    return "\n".join(lines)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], min(len(cell), 80))

    def fmt(row: list[str]) -> str:
        return " | ".join(_truncate(cell, 80).ljust(widths[index]) for index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([fmt(headers), separator, *(fmt(row) for row in rows)])


def _truncate(value: str, max_len: int) -> str:
    return value if len(value) <= max_len else value[: max_len - 3] + "..."


def _missing_expected_entities(files: dict[str, Path]) -> list[str]:
    return sorted(set(ENTITY_SCHEMA_MAP) - set(files))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.environ["BY_DATA_DIR"] = sys.argv[1]
        sys.argv = [sys.argv[0], "-s", sys.argv[0]]
    raise SystemExit(pytest.main(sys.argv[1:] or ["-s", __file__]))