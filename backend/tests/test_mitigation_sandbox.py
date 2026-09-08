from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mitigation_sandbox import MITIGATION_ACTION_TEMPLATES, run_mitigation_scenario  # noqa: E402


def test_expedite_sourcing_mitigation_converts_unmet_to_met() -> None:
    baseline = {
        "dfutoskufcst": pd.DataFrame([{"ITEM": "A", "SKULOC": "D", "DMDGROUP": "C1", "STARTDATE": "2025-01-01", "TOTFCST": 10}]),
        "customerorder": pd.DataFrame(columns=["ORDERID", "CUST", "ITEM", "LOC", "QTY", "DELRDD_CALC_DT", "PRIORITY"]),
        "sourcing": pd.DataFrame([{"ITEM": "A", "SOURCE": "S", "DEST": "D", "PRIORITY": 1, "FACTOR": 0.000005}]),
        "inventory": pd.DataFrame(columns=["ITEM", "LOC", "QTY"]),
        "schedrcpts": pd.DataFrame(columns=["ITEM", "LOC", "SCHED_DATE", "QTY"]),
        "productionmethod": pd.DataFrame(columns=["ITEM", "LOC", "PRODUCTIONMETHOD"]),
        "productionstep": pd.DataFrame(columns=["ITEM", "LOC", "PRODUCTIONMETHOD", "RES", "PRODDUR"]),
        "billofmaterials": pd.DataFrame(columns=["ITEM", "SUBORD", "LOC", "DRAWQTY"]),
        "res": pd.DataFrame(columns=["RES", "LOC"]),
    }
    result = run_mitigation_scenario(
        baseline,
        [{
            "action_type": "EXPEDITE_SOURCING",
            "target": {"ITEM": "A", "SOURCE": "S", "DEST": "D"},
            "parameters": {"capacity_increase_units": 5, "freight_surcharge": 2},
            "description": "+5 units expedite on A S-D",
        }],
        solver_kwargs={"max_late_periods": 0},
        parallel=False,
    )

    assert "EXPEDITE_SOURCING" in MITIGATION_ACTION_TEMPLATES
    assert result["baseline_result"]["summary"]["unmet_qty"] == 5.0
    assert result["what_if_result"]["summary"]["unmet_qty"] == 0.0
    assert result["delta_report"]["unmet_units_converted"] == 5.0
    assert result["delta_report"]["mitigation_cost"] == 10.0
    assert "costs $10" in result["delta_report"]["summary_text"]