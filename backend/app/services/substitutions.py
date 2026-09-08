from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class SubstitutionRule:
    primary_item: str
    substitute_item: str
    loc: str
    customer: Optional[str]
    corridor: Optional[str]
    effective_start: date
    effective_end: date
    priority: int
    ratio: float
    penalty: float


def parse_supersession_rules(
    supersession_df: pd.DataFrame | None,
    items_df: pd.DataFrame | None = None,
    sku_df: pd.DataFrame | None = None,
    as_of: date | None = None,
) -> list[SubstitutionRule]:
    if supersession_df is None or supersession_df.empty:
        return []

    as_of = as_of or date.today()
    item_corridors = _item_corridors(items_df)
    sku_customers = _sku_customers(sku_df)
    rules = []

    for row in supersession_df.to_dict(orient="records"):
        primary = _text(row.get("ITEM"))
        substitute = _text(row.get("ALTITEM") or row.get("SUPERSEDED_ITEM"))
        loc = _text(row.get("LOC"))
        if not primary or not substitute or not loc:
            continue
        if _float(row.get("ENABLEOPT"), 1.0) <= 0:
            continue

        effective_start = _date(row.get("EFF") or row.get("EFFECTIVE_DATE"), date.min)
        effective_end = _date(row.get("DISC") or row.get("EXPIRY_DATE"), date.max)
        if not (effective_start <= as_of <= effective_end):
            continue

        primary_corridor = item_corridors.get(primary)
        substitute_corridor = item_corridors.get(substitute)
        if primary_corridor and substitute_corridor and primary_corridor != substitute_corridor:
            continue

        customer = _text(row.get("DMDGROUP") or row.get("CUSTOMER") or row.get("CUST"))
        allowed_customers = sku_customers.get((primary, loc), set())
        if customer and allowed_customers and customer not in allowed_customers:
            continue

        rules.append(
            SubstitutionRule(
                primary_item=primary,
                substitute_item=substitute,
                loc=loc,
                customer=customer,
                corridor=primary_corridor or substitute_corridor,
                effective_start=effective_start,
                effective_end=effective_end,
                priority=int(_float(row.get("ALTITEMPRIORITY") or row.get("PRIORITY"), 999)),
                ratio=max(_float(row.get("DRAWQTY") or row.get("CONVERSION_FACTOR"), 1.0), 0.0),
                penalty=max(_float(row.get("PENALTY") or row.get("SUBSTITUTION_PENALTY"), 0.0), 0.0),
            )
        )

    return sorted(rules, key=lambda rule: (rule.primary_item, rule.loc, rule.priority, rule.substitute_item))


def rules_to_dataframe(rules: list[SubstitutionRule]) -> pd.DataFrame:
    return pd.DataFrame([rule.__dict__ for rule in rules])


def _item_corridors(items_df: pd.DataFrame | None) -> dict[str, str]:
    if items_df is None or items_df.empty or "ITEM" not in items_df.columns:
        return {}
    corridor_column = "U_CAPACITY_CORRIDOR" if "U_CAPACITY_CORRIDOR" in items_df.columns else None
    if not corridor_column:
        return {}
    return {
        item: corridor
        for item, corridor in (
            (_text(row.get("ITEM")), _text(row.get(corridor_column)))
            for row in items_df.to_dict(orient="records")
        )
        if item and corridor
    }


def _sku_customers(sku_df: pd.DataFrame | None) -> dict[tuple[str, str], set[str]]:
    if sku_df is None or sku_df.empty or not {"ITEM", "LOC", "CUST"}.issubset(sku_df.columns):
        return {}
    result: dict[tuple[str, str], set[str]] = {}
    for row in sku_df.to_dict(orient="records"):
        item = _text(row.get("ITEM"))
        loc = _text(row.get("LOC"))
        customer = _text(row.get("CUST"))
        if item and loc and customer:
            result.setdefault((item, loc), set()).add(customer)
    return result


def _text(value: object) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _float(value: object, default: float) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(value: object, default: date) -> date:
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return default
    return parsed.date()