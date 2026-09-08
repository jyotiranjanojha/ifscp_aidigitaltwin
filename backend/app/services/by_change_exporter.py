from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

import pandas as pd


DEFAULT_KEY_ORDER_BY_ENTITY: dict[str, list[str]] = {
    "sourcing": ["ITEM", "SOURCE", "DEST"],
    "res": ["RES", "LOC"],
    "dfutoskufcst": ["ITEM", "SKULOC", "STARTDATE"],
    "altbillofmaterials": ["ITEM", "SUBORD", "LOC", "ALTSUBORD"],
    "billofmaterials": ["ITEM", "SUBORD", "LOC"],
    "supersession": ["ITEM", "LOC", "ALTITEM", "DMDGROUP"],
}

SCREEN_BY_ENTITY: dict[str, str] = {
    "sourcing": "Supply Chain Network > Sourcing Rules",
    "res": "Manufacturing > Resources",
    "dfutoskufcst": "Demand > DFU to SKU Forecast",
    "altbillofmaterials": "Manufacturing > Alternate Bill of Materials",
    "billofmaterials": "Manufacturing > Bill of Materials",
    "supersession": "Items > Supersession",
}


@dataclass(frozen=True)
class ChangeInstruction:
    screen: str
    entity: str
    entity_key: str
    column: str
    old_value: Any
    new_value: Any
    matched_rows: int
    scenario_justification: str
    financial_impact: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def build_by_patch_archive(
    baseline_datasets: dict[str, pd.DataFrame],
    scenario_deltas: Iterable[dict[str, Any]],
    timestamp: Optional[datetime] = None,
    scenario_id: str = "what_if_scenario",
    default_justification: str = "Planner-approved what-if mitigation scenario",
    financial_impact: Optional[dict[str, Any]] = None,
) -> bytes:
    timestamp = timestamp or datetime.now()
    financial_impact = financial_impact or {}
    export_stamp = timestamp.strftime("%Y%m%d%H%M%S")

    patched_tables, changes = apply_change_set(
        baseline_datasets,
        scenario_deltas,
        default_justification=default_justification,
        financial_impact=financial_impact,
    )
    manifest = build_change_manifest(
        changes,
        scenario_id=scenario_id,
        generated_at=timestamp,
        financial_impact=financial_impact,
    )
    instructions = build_ui_instructions(changes, scenario_id=scenario_id)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entity, df in sorted(patched_tables.items()):
            zf.writestr(f"if_snop_{entity}-{export_stamp}.csv", _to_by_csv(df))
        zf.writestr("change_manifest.json", json.dumps(manifest, indent=2, default=str))
        zf.writestr("BY_UI_Instructions.txt", instructions)
    return archive.getvalue()


def apply_change_set(
    baseline_datasets: dict[str, pd.DataFrame],
    scenario_deltas: Iterable[dict[str, Any]],
    default_justification: str,
    financial_impact: dict[str, Any],
) -> tuple[dict[str, pd.DataFrame], list[ChangeInstruction]]:
    working = {entity.lower(): _normalize_columns(df.copy()) for entity, df in baseline_datasets.items()}
    modified: dict[str, pd.DataFrame] = {}
    changes: list[ChangeInstruction] = []

    for delta in scenario_deltas:
        entity = str(delta.get("entity") or delta.get("type") or "").lower()
        if entity not in working:
            continue
        updates = _delta_updates(entity, delta)
        if not updates:
            continue

        df = working[entity]
        mask = _match_rows(entity, df, delta)
        matched_rows = int(mask.sum())
        if matched_rows == 0:
            continue

        modified[entity] = df
        entity_key = str(delta.get("key") or _key_from_row(entity, df.loc[mask].iloc[0]))
        justification = str(delta.get("justification") or default_justification)
        delta_financial_impact = delta.get("financial_impact") if isinstance(delta.get("financial_impact"), dict) else financial_impact

        for column, new_value in updates.items():
            column = _normalize_column_name(column)
            if column not in df.columns:
                df[column] = pd.NA
            old_value = df.loc[mask, column].iloc[0]
            df[column] = df[column].astype("object")
            df.loc[mask, column] = new_value
            changes.append(
                ChangeInstruction(
                    screen=SCREEN_BY_ENTITY.get(entity, f"Blue Yonder > {entity}"),
                    entity=entity,
                    entity_key=entity_key,
                    column=column,
                    old_value=old_value,
                    new_value=new_value,
                    matched_rows=matched_rows,
                    scenario_justification=justification,
                    financial_impact=delta_financial_impact,
                )
            )

    return modified, changes


def build_change_manifest(
    changes: list[ChangeInstruction],
    scenario_id: str,
    generated_at: datetime,
    financial_impact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "modified_table_count": len({change.entity for change in changes}),
        "change_count": len(changes),
        "financial_impact": financial_impact,
        "changes": [change.to_dict() for change in changes],
    }


def build_ui_instructions(changes: list[ChangeInstruction], scenario_id: str) -> str:
    lines = [
        f"Blue Yonder UI Change Instructions - {scenario_id}",
        "=" * 72,
        "",
    ]
    if not changes:
        lines.append("No matching row changes were generated for this scenario.")
        return "\n".join(lines)

    for index, change in enumerate(changes, start=1):
        lines.extend([
            f"Step {index}: Update {change.entity}",
            f"Screen: {change.screen}",
            f"Entity Key: {change.entity_key}",
            f"Column: {change.column}",
            f"Old Value: {_display_value(change.old_value)}",
            f"New Value: {_display_value(change.new_value)}",
            f"Matched Rows: {change.matched_rows}",
            f"Justification: {change.scenario_justification}",
            f"Financial Impact: {json.dumps(change.financial_impact, default=str)}",
            "",
        ])
    return "\n".join(lines)


def _delta_updates(entity: str, delta: dict[str, Any]) -> dict[str, Any]:
    if isinstance(delta.get("updates"), dict):
        return {_normalize_column_name(column): value for column, value in delta["updates"].items()}
    column = delta.get("column") or delta.get("field")
    if column:
        return {_normalize_column_name(column): delta.get("value")}
    value = delta.get("value")
    if entity == "sourcing":
        return {"FACTOR": max(0.0, 1.0 - _float(value, 0.0))}
    if entity == "res":
        return {"CAPACITY": value}
    if entity == "dfutoskufcst":
        return {"TOTFCST": value}
    if entity == "supersession":
        return {"ENABLEOPT": 1}
    return {}


def _match_rows(entity: str, df: pd.DataFrame, delta: dict[str, Any]) -> pd.Series:
    if "key_columns" in delta and "key_values" in delta:
        key_columns = [_normalize_column_name(column) for column in delta["key_columns"]]
        key_values = [str(value).strip() for value in delta["key_values"]]
    else:
        key_values = str(delta.get("key") or "").split("|")
        key_columns = _default_key_columns(entity, len(key_values))
    if len(key_columns) != len(key_values) or not key_columns:
        return pd.Series(False, index=df.index)
    mask = pd.Series(True, index=df.index)
    for column, value in zip(key_columns, key_values):
        if column not in df.columns:
            return pd.Series(False, index=df.index)
        mask &= df[column].map(_key) == _key(value)
    return mask


def _default_key_columns(entity: str, key_length: int) -> list[str]:
    ordered = DEFAULT_KEY_ORDER_BY_ENTITY.get(entity, [])
    return ordered[:key_length]


def _key_from_row(entity: str, row: pd.Series) -> str:
    columns = DEFAULT_KEY_ORDER_BY_ENTITY.get(entity, [])
    return "|".join(_key(row.get(column)) for column in columns if column in row)


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


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [_normalize_column_name(column) for column in df.columns]
    return df


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


def _key(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _display_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default