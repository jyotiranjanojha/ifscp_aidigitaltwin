from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.substitutions import parse_supersession_rules, rules_to_dataframe  # noqa: E402


def test_parse_supersession_rules_enforces_customer_corridor_and_priority() -> None:
    supersession_df = pd.DataFrame([
        {"ITEM": "A", "LOC": "L1", "ALTITEM": "B", "DMDGROUP": "C1", "ALTITEMPRIORITY": 2, "DRAWQTY": 0.5, "ENABLEOPT": 1},
        {"ITEM": "A", "LOC": "L1", "ALTITEM": "C", "DMDGROUP": "C1", "ALTITEMPRIORITY": 1, "DRAWQTY": 1.0, "ENABLEOPT": 1},
        {"ITEM": "A", "LOC": "L1", "ALTITEM": "D", "DMDGROUP": "C2", "ALTITEMPRIORITY": 3, "DRAWQTY": 1.0, "ENABLEOPT": 1},
        {"ITEM": "A", "LOC": "L1", "ALTITEM": "E", "DMDGROUP": "C1", "ALTITEMPRIORITY": 4, "DRAWQTY": 1.0, "ENABLEOPT": 0},
    ])
    items_df = pd.DataFrame([
        {"ITEM": "A", "U_CAPACITY_CORRIDOR": "CORRIDOR_1"},
        {"ITEM": "B", "U_CAPACITY_CORRIDOR": "CORRIDOR_1"},
        {"ITEM": "C", "U_CAPACITY_CORRIDOR": "CORRIDOR_1"},
        {"ITEM": "D", "U_CAPACITY_CORRIDOR": "CORRIDOR_1"},
        {"ITEM": "E", "U_CAPACITY_CORRIDOR": "CORRIDOR_1"},
    ])
    sku_df = pd.DataFrame([{"ITEM": "A", "LOC": "L1", "CUST": "C1"}])

    rules = parse_supersession_rules(supersession_df, items_df=items_df, sku_df=sku_df, as_of=date(2026, 1, 1))
    rules_df = rules_to_dataframe(rules)

    assert [rule.substitute_item for rule in rules] == ["C", "B"]
    assert rules[1].ratio == 0.5
    assert set(rules_df["substitute_item"]) == {"B", "C"}


def test_parse_supersession_rules_rejects_mismatched_corridor() -> None:
    supersession_df = pd.DataFrame([
        {"ITEM": "A", "LOC": "L1", "ALTITEM": "B", "DMDGROUP": "C1", "ALTITEMPRIORITY": 1, "DRAWQTY": 1, "ENABLEOPT": 1},
    ])
    items_df = pd.DataFrame([
        {"ITEM": "A", "U_CAPACITY_CORRIDOR": "CORRIDOR_1"},
        {"ITEM": "B", "U_CAPACITY_CORRIDOR": "CORRIDOR_2"},
    ])

    assert parse_supersession_rules(supersession_df, items_df=items_df, as_of=date(2026, 1, 1)) == []