import time
import pandas as pd
import pyomo.environ as pyo
from pyomo.contrib.appsi.solvers.highs import Highs as HiGHS
from pyomo.contrib.appsi.base import TerminationCondition as AppsiTerminationCondition
from pyomo.core.expr.numvalue import is_potentially_variable
from typing import Optional
from collections import defaultdict
from logger_config import get_logger

logger = get_logger("solver.lpopt")


def run_lp_optimization(
    sourcing_df: pd.DataFrame,
    sku_df: pd.DataFrame,
    risk_adjustments: dict,
    bom_df: Optional[pd.DataFrame] = None,
    res_df: Optional[pd.DataFrame] = None,
    productionmethod_df: Optional[pd.DataFrame] = None,
    productionstep_df: Optional[pd.DataFrame] = None,
    inventory_df: Optional[pd.DataFrame] = None,
    schedrcpts_df: Optional[pd.DataFrame] = None,
    substitutions_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Full LP optimization using Pyomo + HiGHS solver via APPSI.
    Handles sourcing, production, BOM, resources, inventory, and scheduled receipts.
    """
    t0 = time.perf_counter()
    logger.info("LP solver started | sourcing=%d rows, sku=%d rows", len(sourcing_df), len(sku_df))
    model = pyo.ConcreteModel()

    sourcing_records = sourcing_df.to_dict(orient="records")
    sku_records = sku_df.to_dict(orient="records")

    items = sorted(set(r["ITEM"] for r in sourcing_records))
    sources = sorted(set(r["SOURCE"] for r in sourcing_records))
    dests = sorted(set(r["DEST"] for r in sourcing_records))

    lanes = [(r["ITEM"], r["SOURCE"], r["DEST"]) for r in sourcing_records]
    model.LANES = pyo.Set(initialize=lanes, dimen=3)

    active_skus = sorted(set((r["ITEM"], r["LOC"]) for r in sku_records))
    model.SKUS = pyo.Set(initialize=active_skus, dimen=2)

    base_cost = {(r["ITEM"], r["SOURCE"], r["DEST"]): r["BASE_COST"] for r in sourcing_records}
    max_capacity = {(r["ITEM"], r["SOURCE"], r["DEST"]): r["MAX_CAPACITY"] for r in sourcing_records}

    for (item, source, dest), cap in max_capacity.items():
        adj_key = f"{item}|{source}"
        if adj_key in risk_adjustments:
            max_capacity[(item, source, dest)] = cap * (1 - risk_adjustments[adj_key])

    demand = {(r["ITEM"], r["LOC"]): r["DEMAND"] for r in sku_records}

    scheduled_receipts = defaultdict(float)
    initial_inventory = {}
    safety_stock_lookup = {}
    bom_links = defaultdict(list)

    has_production = productionmethod_df is not None and productionstep_df is not None
    has_bom = bom_df is not None
    has_resources = res_df is not None
    has_inventory = inventory_df is not None
    has_schedrcpts = schedrcpts_df is not None
    has_substitutions = substitutions_df is not None and not substitutions_df.empty
    substitution_records = []
    substitution_keys = []
    substitution_ratio = {}
    substitution_penalty = {}

    if has_substitutions:
        for r in substitutions_df.to_dict(orient="records"):
            primary = r["primary_item"]
            substitute = r["substitute_item"]
            loc = r["loc"]
            key = (primary, substitute, loc)
            substitution_records.append(key)
            substitution_ratio[key] = r.get("ratio", 1.0) or 1.0
            substitution_penalty[key] = r.get("penalty", 0.0) or 0.0
        substitution_keys = sorted(set(substitution_records))
        model.SUBSTITUTIONS = pyo.Set(initialize=substitution_keys, dimen=3)
        model.substitute = pyo.Var(model.SUBSTITUTIONS, domain=pyo.NonNegativeReals)

    if has_production:
        pm_records = productionmethod_df.to_dict(orient="records")
        ps_records = productionstep_df.to_dict(orient="records")

        production_methods = {}
        for r in pm_records:
            key = (r["ITEM"], r["LOC"], r["METHOD"])
            production_methods[key] = {
                "yield": r.get("YIELD_FACTOR", 1.0),
                "setup_time": r.get("SETUP_TIME", 0.0),
                "run_time": r.get("RUN_TIME", 0.0),
                "batch_size": r.get("BATCH_SIZE", 0.0),
            }

        production_steps = defaultdict(list)
        for r in ps_records:
            key = (r["ITEM"], r["LOC"], r["METHOD"])
            production_steps[key].append({
                "step": r["STEP"],
                "resource": r.get("RESOURCE"),
                "setup_time": r.get("SETUP_TIME", 0.0),
                "run_time": r.get("RUN_TIME", 0.0),
                "queue_time": r.get("QUEUE_TIME", 0.0),
                "move_time": r.get("MOVE_TIME", 0.0),
                "yield": r.get("YIELD_FACTOR", 1.0),
            })

        production_keys = list(production_methods.keys())
        model.PROD_KEYS = pyo.Set(initialize=production_keys, dimen=3)
        model.produce = pyo.Var(model.PROD_KEYS, domain=pyo.NonNegativeReals)

        if has_bom:
            bom_records = bom_df.to_dict(orient="records")
            for r in bom_records:
                parent = r["PARENT_ITEM"]
                comp = r["COMPONENT_ITEM"]
                loc = r["LOC"]
                qty = r["QUANTITY_PER"]
                scrap = r.get("SCRAP_FACTOR", 0.0)
                bom_links[(parent, loc)].append((comp, loc, qty * (1 + scrap)))

    if has_resources:
        res_records = res_df.to_dict(orient="records")
        resource_capacity = {}
        resource_cost = {}
        for r in res_records:
            res = r["RESOURCE"]
            loc = r["LOC"]
            cap = r.get("CAPACITY") or 0.0
            eff = r.get("EFFICIENCY") or 1.0
            resource_capacity[(res, loc)] = cap * eff
            resource_cost[(res, loc)] = r.get("COST_PER_HOUR") or 0.0

        model.RESOURCES = pyo.Set(initialize=list(resource_capacity.keys()), dimen=2)

    if has_inventory:
        inv_records = inventory_df.to_dict(orient="records")
        for r in inv_records:
            key = (r["ITEM"], r["LOC"])
            initial_inventory[key] = r.get("ON_HAND", 0.0) + r.get("ON_ORDER", 0.0) - r.get("ALLOCATED", 0.0)
            safety_stock_lookup[key] = r.get("SAFETY_STOCK", 0.0)

    if has_schedrcpts:
        sr_records = schedrcpts_df.to_dict(orient="records")
        for r in sr_records:
            key = (r["ITEM"], r["LOC"])
            scheduled_receipts[key] += r.get("QUANTITY", 0.0)

    model.shipments = pyo.Var(model.LANES, domain=pyo.NonNegativeReals)

    def total_cost_rule(model):
        cost = sum(model.shipments[i, s, d] * base_cost[(i, s, d)] for (i, s, d) in model.LANES)
        if has_production and has_resources:
            for (item, loc, method), pm in production_methods.items():
                pvar = model.produce[item, loc, method]
                for step in production_steps[(item, loc, method)]:
                    res_cost = resource_cost.get((step["resource"], loc), 0.0)
                    run_time = step.get("run_time") or 0.0
                    cost += pvar * run_time * res_cost
        elif has_production:
            for (item, loc, method), pm in production_methods.items():
                var = model.produce[item, loc, method]
                cost += var * (pm.get("run_time") or 0.0) * 0.1
        if has_substitutions:
            for key in model.SUBSTITUTIONS:
                cost += model.substitute[key] * substitution_penalty[key]
        return cost

    model.total_cost = pyo.Objective(rule=total_cost_rule, sense=pyo.minimize)

    def capacity_rule(model, item, source, dest):
        cap = max_capacity.get((item, source, dest), 0)
        if cap <= 0:
            return pyo.Constraint.Skip
        return model.shipments[item, source, dest] <= cap

    model.capacity_constraint = pyo.Constraint(model.LANES, rule=capacity_rule)

    def demand_rule(model, item, dest):
        supply = sum(model.shipments[i, s, d] for (i, s, d) in model.LANES if i == item and d == dest)

        if has_production:
            for (i, l, m), var in model.produce.items():
                if i == item and l == dest:
                    yield_factor = production_methods[(i, l, m)]["yield"]
                    supply += var * yield_factor

            if has_bom:
                for (parent, loc), comps in bom_links.items():
                    if loc == dest:
                        for comp, comp_loc, qty_per in comps:
                            if comp == item:
                                for (pi, pl, pm), pvar in model.produce.items():
                                    if pi == parent and pl == loc:
                                        supply -= pvar * qty_per

        if has_substitutions:
            for primary, substitute, sub_loc in model.SUBSTITUTIONS:
                if primary == item and sub_loc == dest:
                    supply += model.substitute[primary, substitute, sub_loc] * substitution_ratio[(primary, substitute, sub_loc)]

        if has_substitutions:
            for primary, substitute, sub_loc in model.SUBSTITUTIONS:
                if substitute == item and sub_loc == dest:
                    supply -= model.substitute[primary, substitute, sub_loc]

        req = demand.get((item, dest), 0)
        req -= initial_inventory.get((item, dest), 0)
        req -= scheduled_receipts.get((item, dest), 0)
        req = max(req, 0)

        if not is_potentially_variable(supply):
            return pyo.Constraint.Feasible if supply >= req else pyo.Constraint.Infeasible

        return supply >= req

    model.demand_constraint = pyo.Constraint(model.SKUS, rule=demand_rule)

    if has_substitutions:
        def substitution_availability_rule(model, primary, substitute, loc):
            available = initial_inventory.get((substitute, loc), 0)
            available += scheduled_receipts.get((substitute, loc), 0)
            inbound = sum(model.shipments[i, s, d] for (i, s, d) in model.LANES if i == substitute and d == loc)
            produced = 0
            if has_production:
                produced = sum(
                    var for (i, l, _m), var in model.produce.items()
                    if i == substitute and l == loc
                )
            return model.substitute[primary, substitute, loc] <= available + inbound + produced

        model.substitution_availability_constraint = pyo.Constraint(model.SUBSTITUTIONS, rule=substitution_availability_rule)

    if has_resources and has_production:
        def resource_capacity_rule(model, resource, loc):
            total_usage = 0
            for (item, loc_m, method), steps in production_steps.items():
                if loc_m != loc:
                    continue
                for step in steps:
                    if step["resource"] == resource:
                        pvar = model.produce[item, loc_m, method]
                        time_per_unit = step.get("run_time") or 0.0
                        total_usage += pvar * time_per_unit
            cap = resource_capacity.get((resource, loc), float("inf"))
            if not is_potentially_variable(total_usage):
                return pyo.Constraint.Feasible if total_usage <= cap else pyo.Constraint.Infeasible
            return total_usage <= cap

        model.resource_capacity_constraint = pyo.Constraint(model.RESOURCES, rule=resource_capacity_rule)

    if has_inventory:
        def inventory_balance_rule(model, item, loc):
            ending_inv = initial_inventory.get((item, loc), 0)
            ending_inv += scheduled_receipts.get((item, loc), 0)

            if has_production:
                for (i, l, m), var in model.produce.items():
                    if i == item and l == loc:
                        yield_factor = production_methods[(i, l, m)]["yield"]
                        ending_inv += var * yield_factor

            for (i, s, d), var in model.shipments.items():
                if i == item and s == loc:
                    ending_inv -= var
                if i == item and d == loc:
                    ending_inv += var

            if has_bom:
                for (parent, loc_bom), comps in bom_links.items():
                    if loc_bom == loc:
                        for comp, comp_loc, qty_per in comps:
                            if comp == item:
                                for (pi, pl, pm), pvar in model.produce.items():
                                    if pi == parent and pl == loc:
                                        ending_inv -= pvar * qty_per

            if has_substitutions:
                for primary, substitute, sub_loc in model.SUBSTITUTIONS:
                    if substitute == item and sub_loc == loc:
                        ending_inv -= model.substitute[primary, substitute, sub_loc]

            req = demand.get((item, loc), 0)
            ending_inv -= req

            min_inv = safety_stock_lookup.get((item, loc), 0)
            if not is_potentially_variable(ending_inv):
                return pyo.Constraint.Feasible if ending_inv >= min_inv else pyo.Constraint.Infeasible
            return ending_inv >= min_inv

        model.inventory_balance = pyo.Constraint(model.SKUS, rule=inventory_balance_rule)

    solver = HiGHS()
    logger.info("HiGHS solver invoked | lanes=%d | skus=%d | production=%s | resources=%s",
                len(lanes), len(active_skus), has_production, has_resources)
    results = solver.solve(model)
    tc_name = getattr(results.termination_condition, "name", str(results.termination_condition))
    logger.info("HiGHS terminated with: %s", tc_name)

    if results.termination_condition == AppsiTerminationCondition.optimal:
        shipments_result = []
        for (item, source, dest) in model.LANES:
            qty = pyo.value(model.shipments[item, source, dest])
            if qty > 1e-6:
                shipments_result.append({
                    "ITEM": item,
                    "SOURCE": source,
                    "DEST": dest,
                    "QUANTITY": round(qty, 2),
                    "COST": round(qty * base_cost[(item, source, dest)], 2),
                })

        production_result = []
        if has_production:
            for (item, loc, method) in model.PROD_KEYS:
                pvar = model.produce[item, loc, method]
                qty = pvar.value if pvar.value is not None else 0.0
                if qty > 1e-6:
                    production_result.append({
                        "ITEM": item,
                        "LOC": loc,
                        "METHOD": method,
                        "QUANTITY": round(qty, 2),
                    })

        total_cost_val = pyo.value(model.total_cost)

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
            "total_cost": round(total_cost_val, 6),
            "solve_time_seconds": round(getattr(results, "solve_time", 0), 6) if hasattr(results, "solve_time") else 0.0,
        }

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "LP done (optimal) | cost=%.2f | met=%.1f%% | shipments=%d | production=%d | elapsed=%.0fms",
            total_cost_val, met_pct, len(shipments_result), len(production_result), elapsed_ms,
        )

        return {
            "status": "optimal",
            "shipments": shipments_result,
            "production": production_result,
            "substitutions": [
                {
                    "PRIMARY_ITEM": primary,
                    "SUBSTITUTE_ITEM": substitute,
                    "LOC": loc,
                    "QUANTITY": round(pyo.value(model.substitute[primary, substitute, loc]), 2),
                    "RATIO": substitution_ratio[(primary, substitute, loc)],
                    "PENALTY": substitution_penalty[(primary, substitute, loc)],
                }
                for primary, substitute, loc in model.SUBSTITUTIONS
                if pyo.value(model.substitute[primary, substitute, loc]) > 1e-6
            ] if has_substitutions else [],
            "total_cost": round(total_cost_val, 2),
            "solve_time_ms": getattr(results, "solve_time", 0) * 1000 if hasattr(results, "solve_time") else 0,
            "method": "lp_highs",
            "summary": summary,
        }
    elif tc_name == "infeasible":
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.warning("LP infeasible | elapsed=%.0fms", elapsed_ms)
        return {
            "status": "infeasible",
            "error": "Model is infeasible - demand cannot be met with available capacity",
            "method": "lp_highs",
        }
    else:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.error("LP error: %s | elapsed=%.0fms", tc_name, elapsed_ms)
        return {
            "status": "error",
            "error": f"Solver terminated with condition: {tc_name}",
            "method": "lp_highs",
        }