from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from schema_config import PRIMARY_KEY_COLUMNS_BY_ENTITY


DEFAULT_KEY_ORDER_BY_ENTITY: dict[str, list[str]] = {
    "sourcing": ["ITEM", "SOURCE", "DEST"],
    "res": ["RES", "LOC"],
    "dfutoskufcst": ["ITEM", "SKULOC", "STARTDATE"],
    "sku": ["ITEM", "LOC"],
}


@dataclass(frozen=True)
class ExportedPatch:
    entity: str
    key: str
    column: str
    old_value: Any
    new_value: Any
    matched_rows: int


def build_by_export_zip(
    baseline_datasets: dict[str, pd.DataFrame],
    scenario_deltas: Iterable[dict[str, Any]],
    timestamp: Optional[datetime] = None,
) -> bytes:
    """Create a Blue Yonder-compatible ZIP containing patched CSVs and delta_summary.json."""
    timestamp = timestamp or datetime.now()
    export_stamp = timestamp.strftime("%Y%m%d%H%M%S")
    patched, applied = apply_scenario_deltas(baseline_datasets, scenario_deltas)
    summary = {
        "generated_at": timestamp.isoformat(timespec="seconds"),
        "file_count": len(patched),
        "delta_count": len(applied),
        "deltas": [patch.__dict__ for patch in applied],
    }

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entity, df in sorted(patched.items()):
            filename = f"if_snop_{entity}-{export_stamp}.csv"
            zf.writestr(filename, _to_by_csv(df))
        zf.writestr("delta_summary.json", json.dumps(summary, indent=2, default=str))
    return archive.getvalue()


def write_by_export_zip(
    baseline_datasets: dict[str, pd.DataFrame],
    scenario_deltas: Iterable[dict[str, Any]],
    output_path: Path,
    timestamp: Optional[datetime] = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_by_export_zip(baseline_datasets, scenario_deltas, timestamp=timestamp))
    return output_path


def apply_scenario_deltas(
    baseline_datasets: dict[str, pd.DataFrame],
    scenario_deltas: Iterable[dict[str, Any]],
) -> tuple[dict[str, pd.DataFrame], list[ExportedPatch]]:
    patched = {entity: df.copy() for entity, df in baseline_datasets.items()}
    applied: list[ExportedPatch] = []
    for delta in scenario_deltas:
        entity = str(delta.get("entity") or delta.get("type") or "").lower()
        if entity not in patched:
            continue
        df = patched[entity]
        updates = _delta_updates(entity, delta)
        if not updates:
            continue
        mask = _match_delta_rows(entity, df, delta)
        matched_rows = int(mask.sum())
        if matched_rows == 0:
            continue
        key = str(delta.get("key") or "")
        for column, new_value in updates.items():
            if column not in df.columns:
                df[column] = pd.NA
            old_value = df.loc[mask, column].iloc[0] if matched_rows else None
            df[column] = df[column].astype("object")
            df.loc[mask, column] = new_value
            applied.append(ExportedPatch(entity, key, column, old_value, new_value, matched_rows))
    return patched, applied


def _delta_updates(entity: str, delta: dict[str, Any]) -> dict[str, Any]:
    if isinstance(delta.get("updates"), dict):
        return {_normalize_column_name(column): value for column, value in delta["updates"].items()}

    column = delta.get("column") or delta.get("field")
    value = delta.get("value")
    if column:
        return {_normalize_column_name(column): value}

    if entity == "sourcing":
        return {"FACTOR": max(0.0, 1.0 - _float(value, 0.0))}
    if entity == "res":
        return {"CHECKMAXCAP": max(0.0, 1.0 - _float(value, 0.0))}
    if entity == "dfutoskufcst":
        return {"TOTFCST": value}
    return {}


def _match_delta_rows(entity: str, df: pd.DataFrame, delta: dict[str, Any]) -> pd.Series:
    if "key_columns" in delta and "key_values" in delta:
        key_columns = [_normalize_column_name(column) for column in delta["key_columns"]]
        key_values = [str(value).strip() for value in delta["key_values"]]
    else:
        key_values = str(delta.get("key") or "").split("|")
        key_columns = list(delta.get("key_columns") or _default_key_columns(entity, len(key_values)))

    if len(key_columns) != len(key_values) or not key_columns:
        return pd.Series(False, index=df.index)

    mask = pd.Series(True, index=df.index)
    for column, value in zip(key_columns, key_values):
        column = _normalize_column_name(column)
        if column not in df.columns:
            return pd.Series(False, index=df.index)
        mask &= df[column].map(_string_key) == _string_key(value)
    return mask


def _default_key_columns(entity: str, key_length: int) -> list[str]:
    if entity == "sourcing" and key_length == 2:
        return ["ITEM", "SOURCE"]
    if entity == "dfutoskufcst" and key_length == 2:
        return ["ITEM", "SKULOC"]
    ordered = DEFAULT_KEY_ORDER_BY_ENTITY.get(entity)
    if ordered:
        return ordered[:key_length]
    return sorted(PRIMARY_KEY_COLUMNS_BY_ENTITY.get(entity, set()))


def _to_by_csv(df: pd.DataFrame) -> str:
    export_df = df.copy()
    for column in export_df.columns:
        if _looks_like_date_column(column):
            export_df[column] = export_df[column].map(_format_by_date)
    return export_df.to_csv(index=False, sep="|", lineterminator="\n", na_rep="")


def _format_by_date(value: Any) -> Any:
    if value is None or pd.isna(value) or value == "":
        return ""
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return value
    return parsed.strftime("%Y%m%d%H%M%S")


def _looks_like_date_column(column: str) -> bool:
    column = column.upper()
    return column.endswith("DATE") or column.endswith("_DT") or column in {"EFF", "DISC", "STARTDATE", "ENDDATE", "SCHED_DATE", "START_DT", "AVAILDATE"}


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


def _string_key(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default