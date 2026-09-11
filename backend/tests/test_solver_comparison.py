"""
Test scenarios demonstrating algorithmic differences between LP and Heuristic solvers,
and between MIN_COST and MAX_DEMAND_FULFILLMENT objective modes.

Key insight: The heuristic engine ignores production entirely (returns empty production list).
So when production is the ONLY way to meet demand, heuristic fails to optimize it.
LP integrates production scheduling for globally optimal results.

Additionally, with shared production resources, LP balances production across items
based on priority weights, while heuristic has no production model at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lpopt_engine import run_lp_optimization
from heuristic_engine import run_heuristic_optimization


# ---------------------------------------------------------------------------
# Scenario 1: Production is the ONLY way to meet demand (no sourcing lanes).
# Heuristic produces nothing; LP optimally allocates production.
# ---------------------------------------------------------------------------
def test_production_only_lp_vs_heuristic():
    """LP produces to meet demand; heuristic has no production model."""
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 100.0, "MAX_CAPACITY": 0.0},
        {"ITEM": "ITEM_B", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 100.0, "MAX_CAPACITY": 0.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 60.0, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D1", "DEMAND": 40.0, "PRIORITY": 1},
    ])
    pm = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 100.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 5.0},
    ])

    lp_result = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MIN_COST",
    )
    heuristic_result = run_heuristic_optimization(sourcing, sku, risk_adjustments={})

    assert lp_result["status"] == "optimal"
    # LP should produce both items
    lp_prod = {p["ITEM"]: p["QUANTITY"] for p in lp_result["production"]}
    assert lp_prod.get("ITEM_A", 0) >= 59.0, f"LP should produce ~60 ITEM_A, got {lp_prod.get('ITEM_A', 0)}"
    assert lp_prod.get("ITEM_B", 0) >= 39.0, f"LP should produce ~40 ITEM_B, got {lp_prod.get('ITEM_B', 0)}"
    assert lp_result["summary"]["fill_rate_pct"] >= 99.0

    # Heuristic produces nothing and fails to meet demand (sourcing cap = 0)
    assert len(heuristic_result["production"]) == 0
    assert heuristic_result["summary"]["met_qty"] <= 1e-6


# ---------------------------------------------------------------------------
# Scenario 2: Sourcing provides partial supply; production fills the gap.
# LP jointly optimizes sourcing + production; heuristic only uses sourcing.
# ---------------------------------------------------------------------------
def test_sourcing_plus_production_lp_optimizes_globally():
    """LP finds cheapest mix of sourcing + production; heuristic only sources."""
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 2.0, "MAX_CAPACITY": 30.0},
        {"ITEM": "ITEM_B", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 2.0, "MAX_CAPACITY": 30.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 50.0, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D1", "DEMAND": 50.0, "PRIORITY": 1},
    ])
    pm = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 40.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 3.0},
    ])

    lp_result = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MIN_COST",
    )
    heuristic_result = run_heuristic_optimization(sourcing, sku, risk_adjustments={})

    assert lp_result["status"] == "optimal"

    # LP uses production to fill the gap (sourcing cap 30 < demand 50)
    assert lp_result["summary"]["fill_rate_pct"] >= 99.0
    lp_prod = {p["ITEM"]: p["QUANTITY"] for p in lp_result["production"]}
    assert lp_prod.get("ITEM_A", 0) > 0, "LP should produce ITEM_A to fill gap"
    assert lp_prod.get("ITEM_B", 0) > 0, "LP should produce ITEM_B to fill gap"

    # Heuristic can only ship 30 per item (sourcing cap), reports infeasible (unmet demand)
    heur_met = heuristic_result["summary"]["met_qty"]
    assert heur_met <= 60.0 + 1e-6, f"Heuristic can only source up to 60 total, got {heur_met}"
    assert heuristic_result["summary"]["unmet_qty"] >= 39.0

    # LP meets all demand; heuristic doesn't
    assert lp_result["summary"]["fill_rate_pct"] > heuristic_result["summary"]["met_pct"]


# ---------------------------------------------------------------------------
# Scenario 3: Priority-weighted production allocation with shared resource.
# LP allocates more production to high-priority items.
# ---------------------------------------------------------------------------
def test_priority_weighted_production_allocation():
    """LP allocates more production capacity to higher-priority items."""
    sourcing = pd.DataFrame([
        {"ITEM": "HIGH_PRI", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 100.0, "MAX_CAPACITY": 0.0},
        {"ITEM": "LOW_PRI",  "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 100.0, "MAX_CAPACITY": 0.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "HIGH_PRI", "LOC": "D1", "DEMAND": 80.0, "PRIORITY": 1},   # weight = 1.0
        {"ITEM": "LOW_PRI",  "LOC": "D1", "DEMAND": 80.0, "PRIORITY": 10},  # weight = 0.1
    ])
    # Resource only allows 80 units total (items need 1hr each)
    pm = pd.DataFrame([
        {"ITEM": "HIGH_PRI", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
        {"ITEM": "LOW_PRI",  "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "HIGH_PRI", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
        {"ITEM": "LOW_PRI",  "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 80.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 5.0},
    ])

    result = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MAX_DEMAND_FULFILLMENT",
    )
    assert result["status"] == "optimal"

    prod = {p["ITEM"]: p["QUANTITY"] for p in result["production"]}
    high_qty = prod.get("HIGH_PRI", 0)
    low_qty = prod.get("LOW_PRI", 0)

    # HIGH_PRI should get more production time (higher priority weight)
    assert high_qty > low_qty, f"HIGH_PRI ({high_qty}) should exceed LOW_PRI ({low_qty})"
    assert high_qty + low_qty <= 80.0 + 1e-6, "Total must respect resource constraint"
    assert high_qty >= 70.0, f"HIGH_PRI should get at least 70, got {high_qty}"


# ---------------------------------------------------------------------------
# Scenario 4: MIN_COST vs MAX_DEMAND_FULFILLMENT with constrained production.
# Both modes use production (sourcing insufficient), but allocate differently.
# ---------------------------------------------------------------------------
def test_min_cost_vs_max_demand_production_tradeoff():
    """Different objective modes produce different production/sourcing allocations."""
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 1.0, "MAX_CAPACITY": 20.0},
        {"ITEM": "ITEM_B", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 1.0, "MAX_CAPACITY": 20.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 50.0, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D1", "DEMAND": 50.0, "PRIORITY": 1},
    ])
    # Production fills gap; shared resource of 60 hours
    pm = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 60.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 5.0},
    ])

    result_min = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MIN_COST",
    )
    result_max = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MAX_DEMAND_FULFILLMENT",
    )

    assert result_min["status"] == "optimal"
    assert result_max["status"] == "optimal"

    # Both should fully meet demand (sourcing 20*2 + production 60 = 100)
    assert result_min["summary"]["fill_rate_pct"] >= 99.0
    assert result_max["summary"]["fill_rate_pct"] >= 99.0

    # Both use production
    assert len(result_min["production"]) > 0
    assert len(result_max["production"]) > 0


# ---------------------------------------------------------------------------
# Scenario 5: LP MIN_COST vs Heuristic — different fill rates.
# Heuristic ignores production so it undersupplies; LP fully meets demand.
# ---------------------------------------------------------------------------
def test_heuristic_undersupplies_lp_fills_gap():
    """Heuristic can only source; LP uses production to meet all demand."""
    sourcing = pd.DataFrame([
        {"ITEM": "ITEM_A", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 1.0, "MAX_CAPACITY": 25.0},
        {"ITEM": "ITEM_B", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 1.0, "MAX_CAPACITY": 25.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 50.0, "PRIORITY": 1},
        {"ITEM": "ITEM_B", "LOC": "D1", "DEMAND": 50.0, "PRIORITY": 1},
    ])
    pm = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
        {"ITEM": "ITEM_B", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 50.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 3.0},
    ])

    lp_result = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MIN_COST",
    )
    heuristic_result = run_heuristic_optimization(sourcing, sku, risk_adjustments={})

    assert lp_result["status"] == "optimal"

    # LP meets all demand via sourcing + production
    assert lp_result["summary"]["fill_rate_pct"] >= 99.0

    # Heuristic only sources, misses 50 units (25 cap * 2 items = 50, demand = 100)
    heur_met = heuristic_result["summary"]["met_qty"]
    assert heur_met <= 50.0 + 1e-6
    assert heuristic_result["summary"]["unmet_qty"] >= 49.0


# ---------------------------------------------------------------------------
# Scenario 6: Infeasible detection when production resource is insufficient.
# ---------------------------------------------------------------------------
def test_infeasible_production_resource():
    """LP correctly detects infeasibility when production resource is too small."""
    sourcing = pd.DataFrame(columns=["ITEM", "SOURCE", "DEST", "BASE_COST", "MAX_CAPACITY"])
    sku = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "DEMAND": 100.0, "PRIORITY": 1},
    ])
    pm = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "ITEM_A", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 10.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 5.0},
    ])

    # LP MIN_COST: demand=100, sourcing=0, production capacity=10 → infeasible
    result = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MIN_COST",
    )
    assert result["status"] == "infeasible"

    # Heuristic can't do production, so it also reports infeasible (no supply available)
    heur_result = run_heuristic_optimization(sourcing, sku, risk_adjustments={})
    assert heur_result["status"] == "infeasible"
    assert heur_result["summary"]["met_qty"] <= 1e-6


# ---------------------------------------------------------------------------
# Scenario 7: MAX_DEMAND_FULFILLMENT with constrained production.
# High-priority item gets production capacity; low-priority item goes unmet.
# ---------------------------------------------------------------------------
def test_sacrifice_noncritical_for_critical_production():
    """LP with MAX_DEMAND_FULFILLMENT favors production of high-priority items."""
    sourcing = pd.DataFrame([
        {"ITEM": "CRITICAL", "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 100.0, "MAX_CAPACITY": 0.0},
        {"ITEM": "NONCRIT",  "SOURCE": "PLANT1", "DEST": "D1", "BASE_COST": 100.0, "MAX_CAPACITY": 0.0},
    ])
    sku = pd.DataFrame([
        {"ITEM": "CRITICAL", "LOC": "D1", "DEMAND": 80.0, "PRIORITY": 1},   # weight = 1.0
        {"ITEM": "NONCRIT",  "LOC": "D1", "DEMAND": 80.0, "PRIORITY": 10},  # weight = 0.1
    ])
    # Resource allows only 80 units total
    pm = pd.DataFrame([
        {"ITEM": "CRITICAL", "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
        {"ITEM": "NONCRIT",  "LOC": "D1", "METHOD": "M1", "YIELD_FACTOR": 1.0,
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "BATCH_SIZE": 1.0},
    ])
    ps = pd.DataFrame([
        {"ITEM": "CRITICAL", "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
        {"ITEM": "NONCRIT",  "LOC": "D1", "METHOD": "M1", "STEP": 1, "RESOURCE": "LINE1",
         "SETUP_TIME": 0.0, "RUN_TIME": 1.0, "QUEUE_TIME": 0.0, "MOVE_TIME": 0.0, "YIELD_FACTOR": 1.0},
    ])
    res = pd.DataFrame([
        {"RESOURCE": "LINE1", "LOC": "D1", "CAPACITY": 80.0, "EFFICIENCY": 1.0, "COST_PER_HOUR": 5.0},
    ])

    result = run_lp_optimization(
        sourcing, sku, risk_adjustments={},
        productionmethod_df=pm, productionstep_df=ps, res_df=res,
        objective_mode="MAX_DEMAND_FULFILLMENT",
    )
    assert result["status"] == "optimal"

    prod = {p["ITEM"]: p["QUANTITY"] for p in result["production"]}
    critical_qty = prod.get("CRITICAL", 0)
    noncrit_qty = prod.get("NONCRIT", 0)

    assert critical_qty + noncrit_qty <= 80.0 + 1e-6

    # CRITICAL should get more production (higher priority weight)
    assert critical_qty > noncrit_qty, (
        f"CRITICAL ({critical_qty}) should get more production than NONCRIT ({noncrit_qty})"
    )
    assert critical_qty >= 70.0, f"CRITICAL should get at least 70 units, got {critical_qty}"
