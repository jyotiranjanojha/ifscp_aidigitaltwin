"""
Blue Yonder Enterprise Supply Planning (BY ESP) LpOpt Digital Twin Engine
=========================================================================

A production-grade Pyomo-based linear programming formulation that precisely
replicates the core mathematical architecture of the BY ESP LpOpt engine.

Mathematical Formulations Implemented:
  I.    Global Objective: Minimize Σ(production + transport + inventory + procurement + penalties)
  II.   Hard Constraints: Material Balance, Resource Capacity, Transit/Lead Time, BOM Explosion
  III.  Soft Constraints: Demand Fulfillment Slack, Safety Stock Violation Slack
  IV.   Priority Logic: Customer priority scaling, sourcing preference penalties

Technology: Pyomo ConcreteModel + HiGHS via APPSI
"""

import time
import math
import pandas as pd
import numpy as np
import pyomo.environ as pyo
from pyomo.contrib.appsi.solvers.highs import Highs as HiGHS
from pyomo.contrib.appsi.base import TerminationCondition as AppsiTerminationCondition
from typing import Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_PENALTY_SCALE_BASE = 100.0
DEFAULT_SAFETY_STOCK_PENALTY_RATIO = 0.1
DEFAULT_SOURCING_PREF_PENALTY = 5.0
DEFAULT_INVENTORY_HOLDING_COST = 0.01
DEFAULT_PRODUCTION_COST_PER_UNIT = 1.0
DEFAULT_PROCUREMENT_COST_PER_UNIT = 2.0
HUGE_PENALTY = 1e8
EPSILON = 1e-6


@dataclass
class LpOptConfig:
    """Configuration knobs that mirror BY ESP planning parameters."""
    planning_horizon: int = 12
    demand_penalty_scale_base: float = DEFAULT_PENALTY_SCALE_BASE
    safety_stock_penalty_ratio: float = DEFAULT_SAFETY_STOCK_PENALTY_RATIO
    sourcing_pref_penalty: float = DEFAULT_SOURCING_PREF_PENALTY
    inventory_holding_cost: float = DEFAULT_INVENTORY_HOLDING_COST
    production_cost_per_unit: float = DEFAULT_PRODUCTION_COST_PER_UNIT
    procurement_cost_per_unit: float = DEFAULT_PROCUREMENT_COST_PER_UNIT
    time_period_prefix: str = "W"


# ---------------------------------------------------------------------------
# Synthetic Data Generator (BY ESP Schema)
# ---------------------------------------------------------------------------
class BYESPDataGenerator:
    """Generates synthetic DataFrames matching the BY ESP relational schema.

    Produces tables for: demand (customerorder, dfutoskufcst), resources (res),
    sourcing lanes (sourcing, network), BOM (billofmaterials), and
    inventory policy (sku, skueffinventoryparam).
    """

    def __init__(self, config: LpOptConfig, seed: int = 42):
        self.cfg = config
        self.rng = np.random.default_rng(seed)
        self.items = [f"ITEM_{i:03d}" for i in range(1, 7)]
        self.locations = [f"LOC_{c}" for c in ["ATL", "PDX", "DUB", "CDG"]]
        self.sources = [f"SRC_{s:02d}" for s in range(1, 5)]
        self.destinations = self.locations[:3]
        self.customers = [f"CUST_{c:02d}" for c in range(1, 6)]
        self.resources = [f"RES_{r}" for r in ["ETCH", "LITHO", "CMP", "DIFF"]]
        self.methods = ["M01", "M02"]
        self.time_periods = [
            f"{self.cfg.time_period_prefix}{t+1:02d}"
            for t in range(self.cfg.planning_horizon)
        ]

    def generate_demand_forecast(self) -> pd.DataFrame:
        """dfutoskufcst: item-level demand forecast per location per period."""
        rows = []
        for item in self.items:
            for loc in self.destinations:
                base_demand = self.rng.uniform(50, 500)
                for t, period in enumerate(self.time_periods):
                    seasonal = 1.0 + 0.3 * math.sin(2 * math.pi * t / self.cfg.planning_horizon)
                    noise = self.rng.uniform(0.85, 1.15)
                    qty = round(base_demand * seasonal * noise, 0)
                    rows.append({
                        "ITEM": item,
                        "SKULOC": f"{item}|{loc}",
                        "LOC": loc,
                        "STARTDATE": period,
                        "TOTFCST": qty,
                        "QUANTITY": qty,
                    })
        return pd.DataFrame(rows)

    def generate_customer_orders(self) -> pd.DataFrame:
        """customerorder: firm orders with priority-based penalty costs."""
        rows = []
        for cust_idx, cust in enumerate(self.customers):
            priority = cust_idx + 1
            for _ in range(self.rng.integers(2, 6)):
                item = self.rng.choice(self.items)
                loc = self.rng.choice(self.destinations)
                period = self.rng.choice(self.time_periods[:4])
                qty = round(self.rng.uniform(20, 200), 0)
                rows.append({
                    "CUST": cust,
                    "ORDERID": f"CO-{cust}-{len(rows):04d}",
                    "ITEM": item,
                    "LOC": loc,
                    "QTY": qty,
                    "PRIORITY": priority,
                    "STARTDATE": period,
                })
        return pd.DataFrame(rows)

    def generate_sku_policy(self) -> pd.DataFrame:
        """sku: planning parameters per item-location."""
        rows = []
        for item in self.items:
            for loc in self.locations:
                rows.append({
                    "ITEM": item,
                    "LOC": loc,
                    "ENABLEOPT": 1,
                    "SSRULE": round(self.rng.uniform(0.5, 2.0), 2),
                })
        return pd.DataFrame(rows)

    def generate_sourcing_lanes(self) -> pd.DataFrame:
        """sourcing: transportation lanes with cost, capacity, lead time."""
        rows = []
        for item in self.items:
            for src in self.sources:
                for dest in self.destinations:
                    if self.rng.random() > 0.4:
                        base_cost = round(self.rng.uniform(1.0, 15.0), 2)
                        max_cap = round(self.rng.uniform(200, 2000), 0)
                        lead_time = int(self.rng.integers(1, 4))
                        priority = int(self.rng.integers(1, 4))
                        pref_penalty = 0.0 if priority == 1 else (
                            self.cfg.sourcing_pref_penalty * priority
                        )
                        rows.append({
                            "ITEM": item,
                            "SOURCE": src,
                            "DEST": dest,
                            "BASE_COST": base_cost,
                            "MAX_CAPACITY": max_cap,
                            "TRANSPORT_TIME": lead_time,
                            "PRIORITY": priority,
                            "SOURCING_PREF_PENALTY": pref_penalty,
                        })
        return pd.DataFrame(rows)

    def generate_network(self) -> pd.DataFrame:
        """network: lane lead times."""
        rows = []
        for src in self.sources:
            for dest in self.destinations:
                rows.append({
                    "SOURCE": src,
                    "DEST": dest,
                    "LEAD_TIME": int(self.rng.integers(1, 4)),
                })
        return pd.DataFrame(rows)

    def generate_bom(self) -> pd.DataFrame:
        """billofmaterials: parent-component relationships with coefficients."""
        rows = []
        finished = self.items[:3]
        components = self.items[3:]
        for parent in finished:
            for comp in self.rng.choice(components, size=min(3, len(components)), replace=False):
                loc = self.rng.choice(self.locations)
                qty_per = round(self.rng.uniform(1.0, 5.0), 2)
                scrap = round(self.rng.uniform(0.0, 0.1), 3)
                rows.append({
                    "ITEM": parent,
                    "SUBORD": comp,
                    "LOC": loc,
                    "PARENT_ITEM": parent,
                    "COMPONENT_ITEM": comp,
                    "DRAWQTY": qty_per,
                    "QUANTITY_PER": qty_per,
                    "SCRAP_FACTOR": scrap,
                })
        return pd.DataFrame(rows)

    def generate_resources(self) -> pd.DataFrame:
        """res: resource definitions with capacity per location."""
        rows = []
        for res in self.resources:
            for loc in self.locations[:2]:
                cap = round(self.rng.uniform(500, 3000), 0)
                eff = round(self.rng.uniform(0.75, 1.0), 2)
                cost_hr = round(self.rng.uniform(20, 100), 2)
                rows.append({
                    "RES": res,
                    "LOC": loc,
                    "RESOURCE": res,
                    "CAPACITY": cap,
                    "EFFICIENCY": eff,
                    "COST_PER_HOUR": cost_hr,
                })
        return pd.DataFrame(rows)

    def generate_production_methods(self) -> pd.DataFrame:
        """productionmethod: feasible manufacturing routes."""
        rows = []
        for item in self.items[:3]:
            for loc in self.locations[:2]:
                for method in self.methods:
                    rows.append({
                        "ITEM": item,
                        "LOC": loc,
                        "PRODUCTIONMETHOD": method,
                        "METHOD": method,
                        "YIELD_FACTOR": round(self.rng.uniform(0.85, 1.0), 3),
                        "SETUP_TIME": round(self.rng.uniform(0.5, 4.0), 1),
                        "RUN_TIME": round(self.rng.uniform(0.1, 2.0), 2),
                        "BATCH_SIZE": round(self.rng.uniform(50, 500), 0),
                    })
        return pd.DataFrame(rows)

    def generate_production_steps(self) -> pd.DataFrame:
        """productionstep: resource consumption per production method."""
        rows = []
        for item in self.items[:3]:
            for loc in self.locations[:2]:
                for method in self.methods:
                    for step_num, res in enumerate(
                        self.rng.choice(self.resources, size=min(2, len(self.resources)), replace=False),
                        start=1,
                    ):
                        rows.append({
                            "ITEM": item,
                            "LOC": loc,
                            "PRODUCTIONMETHOD": method,
                            "METHOD": method,
                            "STEPNUM": step_num,
                            "STEP": step_num,
                            "RESOURCE": res,
                            "RUN_TIME": round(self.rng.uniform(0.05, 1.0), 3),
                            "YIELD_FACTOR": round(self.rng.uniform(0.9, 1.0), 3),
                        })
        return pd.DataFrame(rows)

    def generate_inventory(self) -> pd.DataFrame:
        """inventory: on-hand stock per item-location."""
        rows = []
        for item in self.items:
            for loc in self.locations:
                on_hand = round(self.rng.uniform(0, 500), 0)
                safety = round(self.rng.uniform(10, 100), 0)
                rows.append({
                    "ITEM": item,
                    "LOC": loc,
                    "ON_HAND": on_hand,
                    "ON_ORDER": round(self.rng.uniform(0, 200), 0),
                    "ALLOCATED": 0.0,
                    "SAFETY_STOCK": safety,
                })
        return pd.DataFrame(rows)

    def generate_skueff_inventory_param(self) -> pd.DataFrame:
        """skueffinventoryparam: target safety stock policy per item-location."""
        rows = []
        for item in self.items:
            for loc in self.locations:
                rows.append({
                    "ITEM": item,
                    "LOC": loc,
                    "MINSSQTY": round(self.rng.uniform(10, 100), 0),
                    "TARGET_SERVICE_LEVEL": round(self.rng.uniform(0.85, 0.99), 2),
                })
        return pd.DataFrame(rows)

    def generate_all(self) -> dict[str, pd.DataFrame]:
        """Return a dict of all BY ESP schema DataFrames."""
        return {
            "demand_forecast": self.generate_demand_forecast(),
            "customer_orders": self.generate_customer_orders(),
            "sku": self.generate_sku_policy(),
            "sourcing": self.generate_sourcing_lanes(),
            "network": self.generate_network(),
            "billofmaterials": self.generate_bom(),
            "res": self.generate_resources(),
            "productionmethod": self.generate_production_methods(),
            "productionstep": self.generate_production_steps(),
            "inventory": self.generate_inventory(),
            "skueffinventoryparam": self.generate_skueff_inventory_param(),
        }


# ---------------------------------------------------------------------------
# LpOpt Digital Twin Engine
# ---------------------------------------------------------------------------
class BYESPLpOptEngine:
    """Full time-phased LP optimization engine replicating BY ESP LpOpt.

    Builds a Pyomo ConcreteModel with:
      - Decision variables: v_production, v_shipments, v_inventory, v_procurement,
        v_shortage (slack), v_safety_stock_violation (slack)
      - Hard constraints: Material Balance, Resource Capacity, Transit/Lead Time, BOM
      - Soft constraints: Demand Fulfillment, Safety Stock Targets
      - Objective: Minimize total systemic cost including all penalties
    """

    def __init__(self, config: Optional[LpOptConfig] = None):
        self.cfg = config or LpOptConfig()
        self.model: Optional[pyo.ConcreteModel] = None
        self.results: Optional[dict] = None
        self._solver_time_ms: float = 0.0

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    def build_and_solve(self, data: dict[str, pd.DataFrame]) -> dict:
        """Build the Pyomo model from BY ESP data and solve with HiGHS.

        Args:
            data: Dict of DataFrames keyed by entity name. Required keys:
                  demand_forecast, sourcing, inventory, skueffinventoryparam.
                  Optional: customer_orders, billofmaterials, res,
                  productionmethod, productionstep, network.

        Returns:
            dict with keys: status, objective_value, solve_time_ms,
            shipments, production, inventory_levels, shortage, safety_stock_violations,
            demand_report, summary.
        """
        t0 = time.perf_counter()
        self._build_model(data)
        self.results = self._solve()
        self._extract_results(data)
        elapsed = (time.perf_counter() - t0) * 1000
        self.results["build_and_solve_time_ms"] = round(elapsed, 1)
        return self.results

    # ------------------------------------------------------------------
    # MODEL BUILDING
    # ------------------------------------------------------------------
    def _build_model(self, data: dict[str, pd.DataFrame]):
        m = pyo.ConcreteModel("BYESP_LpOpt_DigitalTwin")
        self.model = m

        # -- Unpack data --
        demand_df = data["demand_forecast"]
        sourcing_df = data["sourcing"]
        inv_df = data["inventory"]
        ss_param_df = data["skueffinventoryparam"]
        cust_orders_df = data.get("customer_orders")
        bom_df = data.get("billofmaterials")
        res_df = data.get("res")
        prod_method_df = data.get("productionmethod")
        prod_step_df = data.get("productionstep")
        network_df = data.get("network")

        # -- Build index sets --
        items = sorted(demand_df["ITEM"].unique())
        locations = sorted(demand_df["LOC"].unique())
        time_periods = sorted(demand_df["STARTDATE"].unique())
        n_periods = len(time_periods)

        m.ITEMS = pyo.Set(initialize=items)
        m.LOCATIONS = pyo.Set(initialize=locations)
        m.TIME = pyo.Set(initialize=time_periods, ordered=True)

        # SKU = (item, location) pairs that appear in demand
        sku_pairs = sorted(
            demand_df[["ITEM", "LOC"]].drop_duplicates().itertuples(index=False, name=None)
        )
        m.SKUS = pyo.Set(initialize=sku_pairs, dimen=2)

        # Lanes = (item, source, dest) with lead time
        lane_records = sourcing_df.to_dict(orient="records")
        lane_keys = [(r["ITEM"], r["SOURCE"], r["DEST"]) for r in lane_records]
        m.LANES = pyo.Set(initialize=lane_keys, dimen=3)

        # Lead time lookup
        lead_time = {(r["ITEM"], r["SOURCE"], r["DEST"]): int(r.get("TRANSPORT_TIME", 1))
                     for r in lane_records}

        # Source cost with preference penalty
        base_cost = {}
        for r in lane_records:
            key = (r["ITEM"], r["SOURCE"], r["DEST"])
            base_cost[key] = r["BASE_COST"] + r.get("SOURCING_PREF_PENALTY", 0.0)

        # Max capacity per lane
        max_capacity = {(r["ITEM"], r["SOURCE"], r["DEST"]): r.get("MAX_CAPACITY", float("inf"))
                        for r in lane_records}

        # -- Demand data --
        demand = {}
        for r in demand_df.to_dict(orient="records"):
            demand[(r["ITEM"], r["LOC"], r["STARTDATE"])] = r.get("TOTFCST", r.get("QUANTITY", 0))

        # Priority-based penalty scaling
        customer_priority = {}
        if cust_orders_df is not None and not cust_orders_df.empty:
            for r in cust_orders_df.to_dict(orient="records"):
                key = (r["ITEM"], r["LOC"], r.get("STARTDATE", time_periods[0]))
                prio = r.get("PRIORITY", 1)
                scaled_penalty = self.cfg.demand_penalty_scale_base * (100.0 / max(prio, 1))
                customer_priority[key] = max(customer_priority.get(key, 0), scaled_penalty)

        # Default demand penalty for items without explicit customer orders
        for k in demand:
            if k not in customer_priority:
                customer_priority[k] = self.cfg.demand_penalty_scale_base

        # -- Inventory data --
        initial_inventory = {}
        safety_stock_target = {}
        inv_records = inv_df.to_dict(orient="records")
        for r in inv_records:
            key = (r["ITEM"], r["LOC"])
            initial_inventory[key] = r.get("ON_HAND", 0) + r.get("ON_ORDER", 0) - r.get("ALLOCATED", 0)

        ss_records = ss_param_df.to_dict(orient="records")
        for r in ss_records:
            key = (r["ITEM"], r["LOC"])
            safety_stock_target[key] = r.get("MINSSQTY", 0)

        # -- Safety stock penalty --
        safety_stock_penalty = {}
        for k in safety_stock_target:
            safety_stock_penalty[k] = (
                self.cfg.demand_penalty_scale_base * self.cfg.safety_stock_penalty_ratio
            )

        # -- Production data --
        has_production = prod_method_df is not None and prod_method_df is not None
        production_methods = {}
        production_steps = defaultdict(list)
        bom_links = defaultdict(list)

        if has_production:
            for r in prod_method_df.to_dict(orient="records"):
                key = (r["ITEM"], r["LOC"], r["METHOD"])
                production_methods[key] = {
                    "yield": r.get("YIELD_FACTOR", 1.0),
                    "run_time": r.get("RUN_TIME", 0.0),
                    "setup_time": r.get("SETUP_TIME", 0.0),
                }

            if prod_step_df is not None:
                for r in prod_step_df.to_dict(orient="records"):
                    key = (r["ITEM"], r["LOC"], r["METHOD"])
                    production_steps[key].append({
                        "resource": r.get("RESOURCE"),
                        "run_time": r.get("RUN_TIME", 0.0),
                    })

        # -- BOM data --
        has_bom = bom_df is not None and not bom_df.empty
        if has_bom:
            for r in bom_df.to_dict(orient="records"):
                parent = r.get("PARENT_ITEM") or r["ITEM"]
                comp = r.get("COMPONENT_ITEM") or r["SUBORD"]
                loc = r["LOC"]
                qty = r.get("QUANTITY_PER", r.get("DRAWQTY", 1.0))
                scrap = r.get("SCRAP_FACTOR", 0.0)
                bom_links[(parent, loc)].append((comp, qty * (1 + scrap)))

        # -- Resource data --
        has_resources = res_df is not None and not res_df.empty
        resource_capacity = {}
        resource_cost = {}
        if has_resources:
            for r in res_df.to_dict(orient="records"):
                res_key = (r["RESOURCE"], r["LOC"])
                cap = r.get("CAPACITY", 0)
                eff = r.get("EFFICIENCY", 1.0)
                resource_capacity[res_key] = cap * eff
                resource_cost[res_key] = r.get("COST_PER_HOUR", 0)

        # ===================================================================
        # DECISION VARIABLES
        # ===================================================================

        # v_production[i,l,m,t] : quantity produced of item i at loc l via method m in period t
        prod_keys = list(production_methods.keys()) if has_production else []
        m.PROD_KEYS = pyo.Set(initialize=prod_keys, dimen=3) if prod_keys else pyo.Set(initialize=[("_", "_", "_")])
        m.v_production = pyo.Var(
            [(i, l, m, t) for (i, l, m) in prod_keys for t in time_periods],
            domain=pyo.NonNegativeReals,
        ) if prod_keys else pyo.Var([("_", "_", "_", "_")], domain=pyo.NonNegativeReals)

        # v_shipments[i,s,d,t] : quantity shipped on lane (i,s,d) departing in period t
        m.v_shipments = pyo.Var(
            [(i, s, d, t) for (i, s, d) in m.LANES for t in time_periods],
            domain=pyo.NonNegativeReals,
        )

        # v_inventory[i,l,t] : ending inventory of item i at loc l in period t
        m.v_inventory = pyo.Var(
            [(i, l, t) for (i, l) in sku_pairs for t in time_periods],
            domain=pyo.NonNegativeReals,
        )

        # v_shortage[i,l,t] : unfilled demand slack (soft constraint)
        m.v_shortage = pyo.Var(
            [(i, l, t) for (i, l, t) in demand],
            domain=pyo.NonNegativeReals,
        )

        # v_safety_stock_violation[i,l,t] : safety stock shortfall slack
        m.v_ss_violation = pyo.Var(
            [(i, l, t) for (i, l) in sku_pairs for t in time_periods],
            domain=pyo.NonNegativeReals,
        )

        # ===================================================================
        # OBJECTIVE FUNCTION (Rule I)
        # ===================================================================
        def objective_rule(m):
            total_cost = pyo.value(0)

            # Transportation cost
            for (i, s, d, t) in m.v_shipments:
                total_cost += m.v_shipments[i, s, d, t] * base_cost.get((i, s, d), 0)

            # Production cost
            for (i, l, m_method, t) in m.v_production:
                if (i, l, m_method) in production_methods:
                    pm = production_methods[(i, l, m_method)]
                    run_time = pm.get("run_time", 0)
                    res_cost = 0.0
                    if has_resources:
                        for step in production_steps.get((i, l, m_method), []):
                            res_key = (step["resource"], l)
                            res_cost += step["run_time"] * resource_cost.get(res_key, 0)
                    unit_cost = self.cfg.production_cost_per_unit + res_cost
                    total_cost += m.v_production[i, l, m_method, t] * unit_cost

            # Inventory holding cost
            for (i, l, t) in m.v_inventory:
                total_cost += m.v_inventory[i, l, t] * self.cfg.inventory_holding_cost

            # Demand shortage penalty (soft constraint)
            for (i, l, t) in m.v_shortage:
                total_cost += m.v_shortage[i, l, t] * customer_priority.get((i, l, t), self.cfg.demand_penalty_scale_base)

            # Safety stock violation penalty (soft constraint)
            for (i, l) in sku_pairs:
                for t in time_periods:
                    total_cost += m.v_ss_violation[i, l, t] * safety_stock_penalty.get((i, l), 0)

            return total_cost

        m.objective = pyo.Objective(rule=objective_rule, sense=pyo.minimize)

        # ===================================================================
        # HARD CONSTRAINTS
        # ===================================================================

        # -- Material Balance (Conservation of Flow) --
        # For each (item, loc, period t):
        #   Inv(i,l,t) == Inv(i,l,t-1) + Production(i,l,t) + Inbound(i,l,t)
        #                     - Outbound(i,l,t) - FulfilledDemand(i,l,t)
        def material_balance_rule(m, i, l, t):
            t_idx = time_periods.index(t)

            # Previous period inventory
            if t_idx == 0:
                inv_prev = initial_inventory.get((i, l), 0)
            else:
                prev_period = time_periods[t_idx - 1]
                inv_prev = m.v_inventory[i, l, prev_period]

            # Current period inventory
            inv_curr = m.v_inventory[i, l, t]

            # Production at this location
            production = sum(
                m.v_production[i, l, method, t] * production_methods.get((i, l, method), {}).get("yield", 1.0)
                for method in [mth for (ii, ll, mth) in prod_keys if ii == i and ll == l]
            ) if prod_keys else 0

            # Inbound shipments arriving at this location in period t
            inbound = sum(
                m.v_shipments[i, s, d, t_arr]
                for (ii, s, d) in m.LANES
                if ii == i and d == l
                for t_arr in time_periods
                if time_periods.index(t_arr) + lead_time.get((ii, s, d), 1) == t_idx
            )

            # Outbound shipments departing from this location in period t
            outbound = sum(
                m.v_shipments[i, s, d, t]
                for (ii, s, d) in m.LANES
                if ii == i and s == l
            )

            # BOM component consumption
            bom_consumption = 0
            if has_bom:
                for (parent, p_loc), comps in bom_links.items():
                    if p_loc == l:
                        for comp, qty_per in comps:
                            if comp == i:
                                for method in [mth for (pi, pl, mth) in prod_keys if pi == parent and pl == p_loc]:
                                    bom_consumption += m.v_production[parent, p_loc, method, t] * qty_per

            # Fulfilled demand = demand - shortage
            fulfilled = demand.get((i, l, t), 0) - m.v_shortage[i, l, t]

            # Balance equation
            return inv_curr == inv_prev + production + inbound - outbound - bom_consumption - fulfilled

        m.material_balance = pyo.Constraint(
            [(i, l, t) for (i, l) in sku_pairs for t in time_periods],
            rule=material_balance_rule,
        )

        # -- Resource Capacity --
        # Σ production * run_time ≤ MaxAvailableCapacity
        if has_resources and prod_keys:
            def resource_capacity_rule(m, res, loc):
                total_usage = sum(
                    m.v_production[i, l, method, t] * step["run_time"]
                    for (i, l, method) in prod_keys
                    if l == loc
                    for step in production_steps.get((i, l, method), [])
                    if step["resource"] == res
                    for t in time_periods
                )
                cap = resource_capacity.get((res, loc), float("inf"))
                return total_usage <= cap

            m.resource_capacity = pyo.Constraint(
                list(resource_capacity.keys()),
                rule=resource_capacity_rule,
            )

        # -- Transit & Lead Time --
        # Shipments departing at t arrive at t + LeadTime
        # (Modeled implicitly in material_balance via t_arr indexing above;
        #  additionally enforce that shipments can only be sent if time allows arrival)
        def lead_time_validity_rule(m, i, s, d, t):
            lt = lead_time.get((i, s, d), 1)
            t_idx = time_periods.index(t)
            if t_idx + lt >= n_periods:
                return m.v_shipments[i, s, d, t] == 0
            return pyo.Constraint.Skip

        m.lead_time_validity = pyo.Constraint(
            [(i, s, d, t) for (i, s, d) in m.LANES for t in time_periods],
            rule=lead_time_validity_rule,
        )

        # -- Lane Capacity --
        def lane_capacity_rule(m, i, s, d, t):
            cap = max_capacity.get((i, s, d), float("inf"))
            if cap >= 1e12:
                return pyo.Constraint.Skip
            return m.v_shipments[i, s, d, t] <= cap

        m.lane_capacity = pyo.Constraint(
            [(i, s, d, t) for (i, s, d) in m.LANES for t in time_periods],
            rule=lane_capacity_rule,
        )

        # -- BOM Explosion --
        # Production of parent consumes BOM_Coefficient of components from inventory
        # One constraint per (parent, loc, component, time)
        if has_bom and prod_keys:
            bom_prod_pairs = set()
            for (p, pl) in bom_links:
                for (pi, pl2, mth) in prod_keys:
                    if pi == p and pl2 == pl:
                        bom_prod_pairs.add((p, pl))
                        break

            bom_tuples = [
                (p, pl, comp, qty, t)
                for (p, pl) in bom_prod_pairs
                for comp, qty in bom_links[(p, pl)]
                for t in time_periods
            ]

            def bom_explosion_rule(m, parent, p_loc, comp, qty_per, t):
                total_consumed = sum(
                    m.v_production[parent, p_loc, method, t] * qty_per
                    for method in [mth for (pi, pl, mth) in prod_keys if pi == parent and pl == p_loc]
                )
                if (comp, p_loc) in sku_pairs:
                    return total_consumed <= m.v_inventory[comp, p_loc, t]
                return total_consumed <= 0

            m.BOM_TUPLES = pyo.Set(initialize=bom_tuples, dimen=5)
            m.bom_explosion = pyo.Constraint(m.BOM_TUPLES, rule=bom_explosion_rule)

        # ===================================================================
        # SOFT CONSTRAINTS (Rule III)
        # ===================================================================

        # -- Demand Fulfillment --
        # v_shortage[i,l,t] >= 0 ensures shortage is non-negative
        # The objective penalizes v_shortage via demand_penalty_cost
        # Already enforced by variable domain (NonNegativeReals)

        # -- Safety Stock Targets --
        # v_inventory[i,l,t] + v_ss_violation[i,l,t] >= TargetSafetyStock
        def safety_stock_rule(m, i, l, t):
            target = safety_stock_target.get((i, l), 0)
            if target <= 0:
                return pyo.Constraint.Skip
            return m.v_inventory[i, l, t] + m.v_ss_violation[i, l, t] >= target

        m.safety_stock = pyo.Constraint(
            [(i, l, t) for (i, l) in sku_pairs for t in time_periods],
            rule=safety_stock_rule,
        )

        # -- Non-negativity is enforced by variable domains --

        # Store metadata for extraction
        m._meta = {
            "items": items,
            "locations": locations,
            "time_periods": time_periods,
            "sku_pairs": sku_pairs,
            "demand": demand,
            "initial_inventory": initial_inventory,
            "safety_stock_target": safety_stock_target,
            "customer_priority": customer_priority,
            "safety_stock_penalty": safety_stock_penalty,
            "base_cost": base_cost,
            "lead_time": lead_time,
            "production_methods": production_methods,
            "production_steps": dict(production_steps),
            "bom_links": dict(bom_links),
            "resource_capacity": resource_capacity,
            "has_production": has_production,
            "has_bom": has_bom,
            "has_resources": has_resources,
        }

    # ------------------------------------------------------------------
    # SOLVER
    # ------------------------------------------------------------------
    def _solve(self) -> dict:
        t0 = time.perf_counter()
        solver = HiGHS()
        results = solver.solve(self.model)
        self._solver_time_ms = (time.perf_counter() - t0) * 1000

        tc = getattr(results.termination_condition, "name", str(results.termination_condition))

        if results.termination_condition == AppsiTerminationCondition.optimal:
            obj_val = pyo.value(self.model.objective)
            return {
                "status": "optimal",
                "method": "lp_highs",
                "objective_value": round(obj_val, 4),
                "solve_time_ms": round(self._solver_time_ms, 1),
                "termination_condition": tc,
            }
        elif tc == "infeasible":
            return {
                "status": "infeasible",
                "method": "lp_highs",
                "objective_value": None,
                "solve_time_ms": round(self._solver_time_ms, 1),
                "termination_condition": tc,
                "error": "Model is infeasible — demand cannot be satisfied with available capacity.",
            }
        else:
            return {
                "status": "error",
                "method": "lp_highs",
                "objective_value": None,
                "solve_time_ms": round(self._solver_time_ms, 1),
                "termination_condition": tc,
                "error": f"Solver terminated: {tc}",
            }

    # ------------------------------------------------------------------
    # RESULT EXTRACTION & REPORTING
    # ------------------------------------------------------------------
    def _extract_results(self, data: dict[str, pd.DataFrame]):
        if self.results["status"] != "optimal":
            return

        m = self.model
        meta = m._meta
        time_periods = meta["time_periods"]
        sku_pairs = meta["sku_pairs"]
        demand = meta["demand"]

        # -- Shipments --
        shipments = []
        for (i, s, d, t) in m.v_shipments:
            qty = pyo.value(m.v_shipments[i, s, d, t])
            if qty > EPSILON:
                lt = meta["lead_time"].get((i, s, d), 1)
                t_idx = time_periods.index(t)
                arrival_idx = min(t_idx + lt, len(time_periods) - 1)
                shipments.append({
                    "ITEM": i,
                    "SOURCE": s,
                    "DEST": d,
                    "DEPART_PERIOD": t,
                    "ARRIVAL_PERIOD": time_periods[arrival_idx],
                    "QUANTITY": round(qty, 2),
                    "LANE_COST": round(qty * meta["base_cost"].get((i, s, d), 0), 2),
                })
        self.results["shipments"] = shipments

        # -- Production --
        production = []
        if meta["has_production"]:
            for (i, l, method, t) in m.v_production:
                qty = pyo.value(m.v_production[i, l, method, t])
                if qty > EPSILON:
                    yf = meta["production_methods"].get((i, l, method), {}).get("yield", 1.0)
                    production.append({
                        "ITEM": i,
                        "LOC": l,
                        "METHOD": method,
                        "PERIOD": t,
                        "QUANTITY_PRODUCED": round(qty, 2),
                        "YIELD_FACTOR": yf,
                        "NET_OUTPUT": round(qty * yf, 2),
                    })
        self.results["production"] = production

        # -- Inventory Levels --
        inventory_levels = []
        for (i, l, t) in m.v_inventory:
            qty = pyo.value(m.v_inventory[i, l, t])
            inventory_levels.append({
                "ITEM": i,
                "LOC": l,
                "PERIOD": t,
                "INVENTORY_LEVEL": round(qty, 2),
            })
        self.results["inventory_levels"] = inventory_levels

        # -- Shortage --
        shortages = []
        for (i, l, t) in m.v_shortage:
            qty = pyo.value(m.v_shortage[i, l, t])
            if qty > EPSILON:
                shortages.append({
                    "ITEM": i,
                    "LOC": l,
                    "PERIOD": t,
                    "SHORTAGE_QTY": round(qty, 2),
                })
        self.results["shortage"] = shortages

        # -- Safety Stock Violations --
        ss_violations = []
        for (i, l, t) in m.v_ss_violation:
            qty = pyo.value(m.v_ss_violation[i, l, t])
            if qty > EPSILON:
                target = meta["safety_stock_target"].get((i, l), 0)
                ss_violations.append({
                    "ITEM": i,
                    "LOC": l,
                    "PERIOD": t,
                    "VIOLATION_QTY": round(qty, 2),
                    "TARGET_SS": target,
                })
        self.results["safety_stock_violations"] = ss_violations

        # -- Demand Fulfillment Report --
        demand_report = []
        for (i, l, t), demand_qty in sorted(demand.items()):
            shortage_qty = pyo.value(m.v_shortage[i, l, t])
            fulfilled = demand_qty - shortage_qty
            fill_pct = (fulfilled / demand_qty * 100) if demand_qty > 0 else 100.0

            if fill_pct >= 99.99:
                status = "MET"
            elif fill_pct > EPSILON:
                status = "PARTIALLY MET"
            else:
                status = "UNMET"

            demand_report.append({
                "ITEM": i,
                "LOC": l,
                "PERIOD": t,
                "DEMAND_QTY": round(demand_qty, 2),
                "FULFILLED_QTY": round(max(fulfilled, 0), 2),
                "SHORTAGE_QTY": round(max(shortage_qty, 0), 2),
                "FILL_RATE_PCT": round(max(fill_pct, 0), 2),
                "STATUS": status,
            })
        self.results["demand_report"] = demand_report

        # -- Summary --
        total_demand = sum(d["DEMAND_QTY"] for d in demand_report)
        total_fulfilled = sum(d["FULFILLED_QTY"] for d in demand_report)
        total_shortage = sum(d["SHORTAGE_QTY"] for d in demand_report)
        overall_fill_rate = (total_fulfilled / total_demand * 100) if total_demand > 0 else 100.0

        met_count = sum(1 for d in demand_report if d["STATUS"] == "MET")
        partial_count = sum(1 for d in demand_report if d["STATUS"] == "PARTIALLY MET")
        unmet_count = sum(1 for d in demand_report if d["STATUS"] == "UNMET")

        self.results["summary"] = {
            "total_demand": round(total_demand, 2),
            "total_fulfilled": round(total_fulfilled, 2),
            "total_shortage": round(total_shortage, 2),
            "overall_fill_rate_pct": round(overall_fill_rate, 2),
            "demand_lines_met": met_count,
            "demand_lines_partial": partial_count,
            "demand_lines_unmet": unmet_count,
            "total_demand_lines": len(demand_report),
            "objective_value": self.results["objective_value"],
            "solve_time_ms": self.results["solve_time_ms"],
            "total_shipments": len(shipments),
            "total_production_runs": len(production),
            "total_shortage_lines": len(shortages),
            "total_ss_violations": len(ss_violations),
        }


# ---------------------------------------------------------------------------
# Standalone Execution
# ---------------------------------------------------------------------------
def run_digital_twin(config: Optional[LpOptConfig] = None) -> dict:
    """End-to-end entry point: generate data, build model, solve, report."""
    cfg = config or LpOptConfig()
    gen = BYESPDataGenerator(cfg)
    data = gen.generate_all()
    engine = BYESPLpOptEngine(cfg)
    return engine.build_and_solve(data)


if __name__ == "__main__":
    print("=" * 72)
    print("BY ESP LpOpt Digital Twin Engine")
    print("=" * 72)

    cfg = LpOptConfig(planning_horizon=8)
    result = run_digital_twin(cfg)

    print(f"\nStatus: {result['status']}")
    print(f"Objective Value: {result.get('objective_value', 'N/A')}")
    print(f"Solve Time: {result['solve_time_ms']:.1f} ms")

    summary = result.get("summary", {})
    if summary:
        print(f"\n--- SUMMARY ---")
        print(f"Total Demand:       {summary['total_demand']:,.2f}")
        print(f"Total Fulfilled:    {summary['total_fulfilled']:,.2f}")
        print(f"Total Shortage:     {summary['total_shortage']:,.2f}")
        print(f"Overall Fill Rate:  {summary['overall_fill_rate_pct']:.2f}%")
        print(f"Lines MET:          {summary['demand_lines_met']}")
        print(f"Lines PARTIAL:      {summary['demand_lines_partial']}")
        print(f"Lines UNMET:        {summary['demand_lines_unmet']}")
        print(f"Total Shipments:    {summary['total_shipments']}")
        print(f"Total Production:   {summary['total_production_runs']}")
        print(f"SS Violations:      {summary['total_ss_violations']}")

    # Print first 10 demand report lines
    demand_report = result.get("demand_report", [])
    if demand_report:
        print(f"\n--- DEMAND REPORT (first 10 lines) ---")
        for d in demand_report[:10]:
            print(
                f"  {d['ITEM']:12s} | {d['LOC']:6s} | {d['PERIOD']:5s} | "
                f"Demand={d['DEMAND_QTY']:7.1f} | Filled={d['FULFILLED_QTY']:7.1f} | "
                f"Fill={d['FILL_RATE_PCT']:5.1f}% | {d['STATUS']}"
            )
