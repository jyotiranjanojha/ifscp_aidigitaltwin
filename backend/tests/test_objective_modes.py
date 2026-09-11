from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lpopt_engine import run_lp_optimization


def _build_test_data():
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 2.5, "MAX_CAPACITY": 500.0},
        {"ITEM": "ITEM_B", "SOURCE": "PLANT1", "DEST": "D2", "BASE_COST": 4.0, "MAX_CAPACITY": 300.0},
        {"ITEM": "ITEM_A", "SOURCE": "PLANT2", "DEST": "D1", "BASE_COST": 3.0, "MAX_CAPACITY": 400.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 600.0, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D2", "DEMAND": 200.0, "PRIORITY": 1},
    ])
    return sourcing, sku


def test_min_cost_objective():
    sourcing, sku = _build_test_data()
    result = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MIN_COST")
    assert result["status"] == "optimal"
    assert result["objective_mode"] == "MIN_COST"
    summary = result["summary"]
    assert summary["objective_mode"] == "MIN_COST"
    assert summary["total_demand_qty"] == 800.0
    assert summary["met_qty"] > 0
    assert summary["met_pct"] > 0
    assert summary["fill_rate_pct"] > 0
    assert summary["total_landed_cost"] >= 0
    assert summary["total_cost"] >= 0
    assert isinstance(summary["bottlenecked_resources"], list)
    assert isinstance(summary["lane_utilization"], list)


def test_max_demand_fulfillment_objective():
    sourcing, sku = _build_test_data()
    result = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MAX_DEMAND_FULFILLMENT")
    assert result["status"] == "optimal"
    assert result["objective_mode"] == "MAX_DEMAND_FULFILLMENT"
    summary = result["summary"]
    assert summary["objective_mode"] == "MAX_DEMAND_FULFILLMENT"
    assert summary["total_demand_qty"] == 800.0
    assert summary["met_qty"] > 0
    assert summary["met_pct"] > 0
    assert summary["fill_rate_pct"] > 0
    assert summary["total_landed_cost"] >= 0
    assert summary["total_cost"] >= 0
    assert isinstance(summary["bottlenecked_resources"], list)
    assert isinstance(summary["lane_utilization"], list)


def test_priority_weighting():
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 1.0, "MAX_CAPACITY": 100.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 200.0, "PRIORITY": 1},
    ])
    result = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MAX_DEMAND_FULFILLMENT")
    assert result["status"] == "optimal"
    summary = result["summary"]
    assert summary["unmet_qty"] >= 0


def test_consistent_summary_schema():
    sourcing, sku = _build_test_data()
    result_min = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MIN_COST")
    result_max = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MAX_DEMAND_FULFILLMENT")
    min_summary = result_min["summary"]
    max_summary = result_max["summary"]
    expected_keys = {
        "objective_mode", "total_demand_qty", "met_qty", "met_pct",
        "late_qty", "late_pct", "avg_delay_days", "unmet_qty", "unmet_pct",
        "total_supplied_qty", "fill_rate_pct", "total_landed_cost", "total_cost",
        "bottlenecked_resources", "lane_utilization", "solve_time_seconds",
    }
    assert set(min_summary.keys()) == expected_keys
    assert set(max_summary.keys()) == expected_keys


def test_capacity_constraint():
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 1.0, "MAX_CAPACITY": 50.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 200.0, "PRIORITY": 1},
    ])
    result = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MAX_DEMAND_FULFILLMENT")
    assert result["status"] == "optimal"
    total_shipped = sum(s["QUANTITY"] for s in result["shipments"])
    assert total_shipped <= 50.0 + 1e-6


def test_risk_adjustment():
    sourcing, sku = _build_test_data()
    result_before = run_lp_optimization(sourcing, sku, risk_adjustments={}, objective_mode="MIN_COST")
    result_after = run_lp_optimization(sourcing, sku, risk_adjustments={"ITEM_A|PLANT1": 0.5}, objective_mode="MIN_COST")
    assert result_before["status"] == "optimal"
    assert result_after["status"] == "optimal"
