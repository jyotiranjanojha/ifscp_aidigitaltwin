import time
import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from collections import defaultdict
from logger_config import get_logger

logger = get_logger("solver.heuristic")


def run_heuristic_optimization(
    sourcing_df: pd.DataFrame,
    sku_df: pd.DataFrame,
    risk_adjustments: dict,
    bom_df: Optional[pd.DataFrame] = None,
    res_df: Optional[pd.DataFrame] = None,
    productionmethod_df: Optional[pd.DataFrame] = None,
    productionstep_df: Optional[pd.DataFrame] = None,
    inventory_df: Optional[pd.DataFrame] = None,
    schedrcpts_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Greedy cost-minimization heuristic for supply planning.
    Used as a fast fallback when LP solver is unavailable or for warm-starts.
    """
    t0 = time.perf_counter()
    logger.info("Heuristic solver started | sourcing=%d rows, sku=%d rows", len(sourcing_df), len(sku_df))
    sourcing_records = sourcing_df.to_dict(orient="records")
    sku_records = sku_df.to_dict(orient="records")

    base_cost = {(r["ITEM"], r["SOURCE"], r["DEST"]): r["BASE_COST"] for r in sourcing_records}
    max_capacity = {(r["ITEM"], r["SOURCE"], r["DEST"]): r["MAX_CAPACITY"] for r in sourcing_records}

    for (item, source, dest), cap in max_capacity.items():
        adj_key = f"{item}|{source}"
        if adj_key in risk_adjustments:
            max_capacity[(item, source, dest)] = cap * (1 - risk_adjustments[adj_key])

    demand = {(r["ITEM"], r["LOC"]): r["DEMAND"] for r in sku_records}

    initial_inventory = {}
    scheduled_receipts = defaultdict(float)
    safety_stock = {}

    if inventory_df is not None:
        for r in inventory_df.to_dict(orient="records"):
            key = (r["ITEM"], r["LOC"])
            initial_inventory[key] = r.get("ON_HAND", 0.0) + r.get("ON_ORDER", 0.0) - r.get("ALLOCATED", 0.0)
            safety_stock[key] = r.get("SAFETY_STOCK", 0.0)

    if schedrcpts_df is not None:
        for r in schedrcpts_df.to_dict(orient="records"):
            key = (r["ITEM"], r["LOC"])
            scheduled_receipts[key] += r.get("QUANTITY", 0.0)

    lanes_by_dest = defaultdict(list)
    for (item, source, dest), cost in base_cost.items():
        lanes_by_dest[(item, dest)].append((source, cost, max_capacity.get((item, source, dest), 0)))

    for key in lanes_by_dest:
        lanes_by_dest[key].sort(key=lambda x: x[1])

    shipments_result = []
    remaining_demand = {}

    for (item, dest), req in demand.items():
        available = initial_inventory.get((item, dest), 0) + scheduled_receipts.get((item, dest), 0)
        safety = safety_stock.get((item, dest), 0)
        net_demand = max(req + safety - available, 0.0)
        remaining_demand[(item, dest)] = net_demand

    total_cost = 0.0

    for (item, dest), lanes in lanes_by_dest.items():
        need = remaining_demand.get((item, dest), 0)
        if need <= 0:
            continue

        for source, cost, cap in lanes:
            if need <= 0:
                break
            qty = min(need, cap)
            if qty > 1e-6:
                shipments_result.append({
                    "ITEM": item,
                    "SOURCE": source,
                    "DEST": dest,
                    "QUANTITY": round(qty, 2),
                    "COST": round(qty * cost, 2),
                })
                total_cost += qty * cost
                need -= qty

        remaining_demand[(item, dest)] = need

    infeasible = any(v > 1e-6 for v in remaining_demand.values())

    total_demand_qty = sum(demand.values())
    met_qty = sum(s["QUANTITY"] for s in shipments_result)
    unmet_qty = max(total_demand_qty - met_qty, 0.0)
    met_pct = (met_qty / total_demand_qty * 100) if total_demand_qty > 0 else 0.0
    unmet_pct = (unmet_qty / total_demand_qty * 100) if total_demand_qty > 0 else 0.0

    summary = {
        "total_demand_qty": round(total_demand_qty, 6),
        "met_qty": round(met_qty, 6),
        "met_pct": round(met_pct, 6),
        "late_qty": 0.0,
        "late_pct": 0.0,
        "avg_delay_days": 0.0,
        "unmet_qty": round(unmet_qty, 6),
        "unmet_pct": round(unmet_pct, 6),
        "total_cost": round(total_cost, 6),
        "solve_time_seconds": 0.0,
    }

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Heuristic done | status=%s | cost=%.2f | met=%.1f%% | shipments=%d | elapsed=%.0fms",
        "infeasible" if infeasible else "optimal",
        total_cost, met_pct, len(shipments_result), elapsed_ms,
    )

    return {
        "status": "infeasible" if infeasible else "optimal",
        "shipments": shipments_result,
        "production": [],
        "total_cost": round(total_cost, 2),
        "solve_time_ms": 0,
        "method": "greedy_heuristic",
        "summary": summary,
    }