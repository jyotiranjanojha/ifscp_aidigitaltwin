from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

import duckdb
import pandas as pd
import pyomo.environ as pyo
from pyomo.contrib.appsi.solvers.highs import Highs as HiGHS


DEFAULT_LANE_CAPACITY = 1_000_000.0
DEFAULT_RESOURCE_CAPACITY = 24.0
DEFAULT_LATE_PENALTY = 10.0
DEFAULT_SHORTAGE_PENALTY = 1_000_000.0
DEFAULT_PRODUCTION_COST = 0.1
DEFAULT_HOLDING_COST = 0.0


@dataclass(frozen=True)
class DemandEngineResult:
    status: str
    method: str
    summary: dict[str, float]
    pegging_records: list[dict[str, Any]]
    shipments: list[dict[str, Any]]
    production: list[dict[str, Any]]
    total_cost: float
    solve_time_ms: float
    diagnostics: list[dict[str, Any]]


class DemandPeggingEngine:
    """Pyomo demand pegging model with on-time, late, and unmet demand states."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        max_late_periods: Optional[int] = 7,
        late_penalty: float = DEFAULT_LATE_PENALTY,
        shortage_penalty: float = DEFAULT_SHORTAGE_PENALTY,
        production_cost: float = DEFAULT_PRODUCTION_COST,
        holding_cost: float = DEFAULT_HOLDING_COST,
    ) -> None:
        self.conn = conn
        self.max_late_periods = max_late_periods
        self.late_penalty = late_penalty
        self.shortage_penalty = shortage_penalty
        self.production_cost = production_cost
        self.holding_cost = holding_cost
        self.data: dict[str, Any] = {}

    def run(self) -> dict[str, Any]:
        started = time.perf_counter()
        self.data = self._build_data()
        model = self._build_model(self.data)
        result = HiGHS().solve(model)
        solve_time = time.perf_counter() - started
        termination = getattr(result.termination_condition, "name", str(result.termination_condition)).lower()
        result_dict = self._format_result(model, termination, solve_time).__dict__
        try:
            from app.services.bottleneck_tracer import trace_bottlenecks

            result_dict["diagnostics"] = trace_bottlenecks(model, self.data)
        except Exception:
            result_dict["diagnostics"] = []
        return result_dict

    def _build_data(self) -> dict[str, Any]:
        demand_df = self._demand_streams()
        sourcing_df = self._table("sourcing")
        inventory_df = self._table("inventory")
        schedrcpts_df = self._table("schedrcpts")
        productionmethod_df = self._table("productionmethod")
        productionstep_df = self._table("productionstep")
        bom_df = self._table("billofmaterials")
        res_df = self._table("res")

        periods = self._planning_periods(demand_df["REQ_T"].unique().tolist())
        if not periods:
            raise ValueError("No demand found in customerorder or dfutoskufcst")

        demand = {
            (row["ITEM"], row["LOC"], row["CUSTOMER"], row["REQ_T"]): float(row["QTY"])
            for row in demand_df.to_dict(orient="records")
            if float(row["QTY"]) > 0
        }
        priority_weight = {
            (row["ITEM"], row["LOC"], row["CUSTOMER"], row["REQ_T"]): self._priority_weight(row["PRIORITY"])
            for row in demand_df.to_dict(orient="records")
            if float(row["QTY"]) > 0
        }

        lanes = []
        lane_cost = {}
        lane_capacity = {}
        for row in sourcing_df.to_dict(orient="records"):
            item = _text(row.get("ITEM"))
            source = _text(row.get("SOURCE"))
            dest = _text(row.get("DEST"))
            if not item or not source or not dest:
                continue
            lane = (item, source, dest)
            lanes.append(lane)
            lane_cost[lane] = max(_float(row.get("BASE_COST") or row.get("PRIORITY"), 1.0), 0.0)
            if "MAX_CAPACITY" in sourcing_df.columns and pd.notna(row.get("MAX_CAPACITY")):
                base_cap = max(_float(row.get("MAX_CAPACITY"), 0.0), 0.0)
            else:
                base_cap = max(_float(row.get("FACTOR"), 1.0), 0.0) * DEFAULT_LANE_CAPACITY
            for period in periods:
                lane_capacity[(item, source, dest, period)] = base_cap

        inventory = defaultdict(float)
        if not inventory_df.empty:
            for row in inventory_df.to_dict(orient="records"):
                item = _text(row.get("ITEM"))
                loc = _text(row.get("LOC"))
                if item and loc:
                    inventory[(item, loc)] += max(_float(row.get("ON_HAND") or row.get("QTY"), 0.0), 0.0)

        scheduled_receipts = defaultdict(float)
        if not schedrcpts_df.empty:
            for row in schedrcpts_df.to_dict(orient="records"):
                item = _text(row.get("ITEM"))
                loc = _text(row.get("LOC"))
                period = _period(row.get("DUE_DATE") or row.get("SCHED_DATE"))
                if item and loc and period in periods:
                    scheduled_receipts[(item, loc, period)] += max(_float(row.get("QUANTITY") or row.get("QTY"), 0.0), 0.0)

        production_methods = self._production_methods(productionmethod_df)
        production_steps = self._production_steps(productionstep_df)
        resource_capacity = self._resource_capacity(res_df, periods)
        bom_links = self._bom_links(bom_df)
        late_keys = self._late_keys(demand, periods)

        return {
            "periods": periods,
            "period_index": {period: idx for idx, period in enumerate(periods)},
            "demand": demand,
            "demand_keys": sorted(demand),
            "priority_weight": priority_weight,
            "late_keys": late_keys,
            "lanes": sorted(set(lanes)),
            "lane_cost": lane_cost,
            "lane_capacity": lane_capacity,
            "inventory": inventory,
            "scheduled_receipts": scheduled_receipts,
            "production_methods": production_methods,
            "production_steps": production_steps,
            "resource_capacity": resource_capacity,
            "resources": sorted({(res, loc) for res, loc, _period in resource_capacity}),
            "bom_links": bom_links,
        }

    def _demand_streams(self) -> pd.DataFrame:
        rows = []
        customerorder = self._table("customerorder")
        if not customerorder.empty:
            for idx, row in enumerate(customerorder.to_dict(orient="records"), start=1):
                item = _text(row.get("ITEM"))
                loc = _text(row.get("LOC"))
                qty = _float(row.get("ORDERQTY") or row.get("QUANTITY") or row.get("QTY"), 0.0)
                req_t = _period(row.get("SHIPDATE") or row.get("DELRDD_CALC_DT") or row.get("GI_DT") or row.get("U_CGID_DT"))
                if item and loc and qty > 0 and req_t:
                    rows.append({
                        "ORDER_ID": _text(row.get("ORDERID") or row.get("ORDER_ID")) or f"CO-{idx}",
                        "CUSTOMER": _text(row.get("CUSTOMER") or row.get("CUST") or row.get("DMDGROUP")) or "UNKNOWN",
                        "ITEM": item,
                        "LOC": loc,
                        "REQ_T": req_t,
                        "QTY": qty,
                        "PRIORITY": int(_float(row.get("PRIORITY"), 1.0)),
                        "DEMAND_TYPE": "CUSTOMER_ORDER",
                    })

        forecast = self._table("dfutoskufcst")
        if not forecast.empty:
            for idx, row in enumerate(forecast.to_dict(orient="records"), start=1):
                item = _text(row.get("ITEM"))
                loc = _text(row.get("LOC") or row.get("SKULOC"))
                qty = _float(row.get("QTY") or row.get("QUANTITY") or row.get("TOTFCST"), 0.0)
                req_t = _period(row.get("STARTDATE") or row.get("FCST_DATE"))
                if item and loc and qty > 0 and req_t:
                    rows.append({
                        "ORDER_ID": _text(row.get("DFU") or row.get("ORDER_ID")) or f"FCST-{idx}",
                        "CUSTOMER": _text(row.get("DMDGROUP") or row.get("CUSTOMER") or row.get("CUST")) or "FORECAST",
                        "ITEM": item,
                        "LOC": loc,
                        "REQ_T": req_t,
                        "QTY": qty,
                        "PRIORITY": int(_float(row.get("PRIORITY"), 999.0)),
                        "DEMAND_TYPE": "FORECAST",
                    })

        if not rows:
            return pd.DataFrame(columns=["ORDER_ID", "CUSTOMER", "ITEM", "LOC", "REQ_T", "QTY", "PRIORITY", "DEMAND_TYPE"])
        df = pd.DataFrame(rows)
        return df.groupby(["CUSTOMER", "ITEM", "LOC", "REQ_T"], as_index=False).agg(
            ORDER_ID=("ORDER_ID", "first"),
            QTY=("QTY", "sum"),
            PRIORITY=("PRIORITY", "min"),
            DEMAND_TYPE=("DEMAND_TYPE", "first"),
        )

    def _build_model(self, data: dict[str, Any]) -> pyo.ConcreteModel:
        model = pyo.ConcreteModel()
        model.T = pyo.Set(initialize=data["periods"])
        model.LANES = pyo.Set(initialize=data["lanes"], dimen=3)
        model.DEMAND = pyo.Set(initialize=data["demand_keys"], dimen=4)
        model.LATE = pyo.Set(initialize=data["late_keys"], dimen=5)
        model.PROD = pyo.Set(initialize=data["production_methods"], dimen=3)
        model.RESOURCES = pyo.Set(initialize=data["resources"], dimen=2)

        model.Ship = pyo.Var(model.LANES, model.T, domain=pyo.NonNegativeReals)
        model.Produce = pyo.Var(model.PROD, model.T, domain=pyo.NonNegativeReals)
        model.MetDemand = pyo.Var(model.DEMAND, domain=pyo.NonNegativeReals)
        model.LateDemand = pyo.Var(model.LATE, domain=pyo.NonNegativeReals)
        model.UnmetDemand = pyo.Var(model.DEMAND, domain=pyo.NonNegativeReals)

        def objective_rule(m):
            sourcing_cost = sum(
                m.Ship[item, source, dest, t] * data["lane_cost"].get((item, source, dest), 1.0)
                for item, source, dest in m.LANES
                for t in m.T
            )
            production_cost = sum(m.Produce[item, loc, method, t] * self.production_cost for item, loc, method in m.PROD for t in m.T)
            late_cost = sum(
                self.late_penalty * self._period_lag(req_t, ship_t) * m.LateDemand[item, loc, cust, req_t, ship_t]
                for item, loc, cust, req_t, ship_t in m.LATE
            )
            shortage_cost = sum(
                self.shortage_penalty * data["priority_weight"].get((item, loc, cust, req_t), 1.0) * m.UnmetDemand[item, loc, cust, req_t]
                for item, loc, cust, req_t in m.DEMAND
            )
            holding_cost = self.holding_cost * sum(m.Ship[item, source, dest, t] for item, source, dest in m.LANES for t in m.T)
            return sourcing_cost + production_cost + holding_cost + late_cost + shortage_cost

        model.TotalCost = pyo.Objective(rule=objective_rule, sense=pyo.minimize)

        def demand_conservation_rule(m, item, loc, cust, req_t):
            late = sum(m.LateDemand[item, loc, cust, req_t, ship_t] for i, l, c, r, ship_t in m.LATE if (i, l, c, r) == (item, loc, cust, req_t))
            return m.MetDemand[item, loc, cust, req_t] + late + m.UnmetDemand[item, loc, cust, req_t] == data["demand"][(item, loc, cust, req_t)]

        model.DemandConservation = pyo.Constraint(model.DEMAND, rule=demand_conservation_rule)

        def lane_capacity_rule(m, item, source, dest, t):
            return m.Ship[item, source, dest, t] <= data["lane_capacity"].get((item, source, dest, t), 0.0)

        model.LaneCapacity = pyo.Constraint(model.LANES, model.T, rule=lane_capacity_rule)

        def supply_balance_rule(m, item, loc, t):
            on_time = sum(m.MetDemand[i, l, cust, req_t] for i, l, cust, req_t in m.DEMAND if i == item and l == loc and req_t == t)
            late_shipped = sum(m.LateDemand[i, l, cust, req_t, ship_t] for i, l, cust, req_t, ship_t in m.LATE if i == item and l == loc and ship_t == t)
            inbound = sum(m.Ship[i, source, dest, ship_t] for i, source, dest in m.LANES for ship_t in m.T if i == item and dest == loc and ship_t == t)
            produced = sum(m.Produce[i, prod_loc, method, prod_t] for i, prod_loc, method in m.PROD for prod_t in m.T if i == item and prod_loc == loc and prod_t == t)
            available = data["inventory"].get((item, loc), 0.0) + data["scheduled_receipts"].get((item, loc, t), 0.0)
            return on_time + late_shipped <= inbound + produced + available

        model.SUPPLY_KEYS = pyo.Set(initialize=self._supply_keys(data), dimen=3)
        model.SupplyBalance = pyo.Constraint(model.SUPPLY_KEYS, rule=supply_balance_rule)

        def resource_capacity_rule(m, res, loc, t):
            usage = 0
            for (item, prod_loc, method), steps in data["production_steps"].items():
                if prod_loc != loc:
                    continue
                for step_res, hours_per_unit in steps:
                    if step_res == res:
                        usage += m.Produce[item, prod_loc, method, t] * hours_per_unit
            return usage <= data["resource_capacity"].get((res, loc, t), DEFAULT_RESOURCE_CAPACITY)

        model.ResourceCapacity = pyo.Constraint(model.RESOURCES, model.T, rule=resource_capacity_rule)

        model.BOM_KEYS = pyo.Set(initialize=sorted(data["bom_links"]), dimen=2)

        def bom_explosion_rule(m, parent_item, loc, t):
            required = sum(
                m.Produce[parent_item, loc, method, t] * qty_per
                for item, prod_loc, method in m.PROD
                for _component, qty_per in data["bom_links"].get((parent_item, loc), [])
                if item == parent_item and prod_loc == loc
            )
            available = sum(data["inventory"].get((component, loc), 0.0) for component, _qty_per in data["bom_links"].get((parent_item, loc), []))
            return required <= available

        model.BomExplosion = pyo.Constraint(model.BOM_KEYS, model.T, rule=bom_explosion_rule)
        return model

    def _format_result(self, model: pyo.ConcreteModel, termination: str, solve_time: float) -> DemandEngineResult:
        records = []
        total_demand = sum(self.data["demand"].values())
        met_qty = 0.0
        late_qty = 0.0
        unmet_qty = 0.0
        weighted_late_days = 0.0

        for item, loc, cust, req_t in model.DEMAND:
            met = pyo.value(model.MetDemand[item, loc, cust, req_t]) or 0.0
            unmet = pyo.value(model.UnmetDemand[item, loc, cust, req_t]) or 0.0
            if met > 1e-6:
                met_qty += met
                records.append(self._record(item, loc, cust, req_t, req_t, "MET", 0, met))
            for i, l, c, r, ship_t in model.LATE:
                if (i, l, c, r) != (item, loc, cust, req_t):
                    continue
                late = pyo.value(model.LateDemand[item, loc, cust, req_t, ship_t]) or 0.0
                if late > 1e-6:
                    days = self._period_lag(req_t, ship_t)
                    late_qty += late
                    weighted_late_days += late * days
                    records.append(self._record(item, loc, cust, req_t, ship_t, "LATE_MET", days, late))
            if unmet > 1e-6:
                unmet_qty += unmet
                records.append(self._record(item, loc, cust, req_t, None, "UNMET", 0, unmet))

        total_cost = pyo.value(model.TotalCost) or 0.0
        revenue_at_risk = unmet_qty * self.shortage_penalty
        summary = {
            "total_demand_qty": round(total_demand, 6),
            "met_qty": round(met_qty, 6),
            "met_pct": _pct(met_qty, total_demand),
            "late_qty": round(late_qty, 6),
            "late_pct": _pct(late_qty, total_demand),
            "avg_delay_days": round(weighted_late_days / late_qty, 6) if late_qty else 0.0,
            "unmet_qty": round(unmet_qty, 6),
            "unmet_pct": _pct(unmet_qty, total_demand),
            "revenue_at_risk": round(revenue_at_risk, 6),
            "total_cost": round(total_cost, 6),
            "solve_time_seconds": round(solve_time, 6),
        }
        return DemandEngineResult(
            status="optimal" if termination == "optimal" else termination,
            method="pyomo_highs_tri_state_demand_pegging",
            summary=summary,
            pegging_records=records,
            shipments=self._shipments(model),
            production=self._production(model),
            total_cost=summary["total_cost"],
            solve_time_ms=round(solve_time * 1000, 3),
            diagnostics=[],
        )

    def _record(self, item: str, loc: str, cust: str, req_t: str, ship_t: Optional[str], status: str, delay_days: int, qty: float) -> dict[str, Any]:
        return {
            "order_id": f"{item}|{loc}|{cust}|{req_t}",
            "item": item,
            "customer": cust,
            "loc": loc,
            "req_date": req_t,
            "ship_date": ship_t,
            "status": status,
            "delay_days": delay_days,
            "allocated_qty": round(qty, 6),
        }

    def _shipments(self, model: pyo.ConcreteModel) -> list[dict[str, Any]]:
        rows = []
        for item, source, dest in model.LANES:
            for period in model.T:
                qty = pyo.value(model.Ship[item, source, dest, period]) or 0.0
                if qty > 1e-6:
                    cost = qty * self.data["lane_cost"].get((item, source, dest), 1.0)
                    rows.append({"ITEM": item, "SOURCE": source, "DEST": dest, "PERIOD": period, "QUANTITY": round(qty, 6), "COST": round(cost, 6)})
        return rows

    def _production(self, model: pyo.ConcreteModel) -> list[dict[str, Any]]:
        rows = []
        for item, loc, method in model.PROD:
            for period in model.T:
                qty = pyo.value(model.Produce[item, loc, method, period]) or 0.0
                if qty > 1e-6:
                    rows.append({"ITEM": item, "LOC": loc, "METHOD": method, "PERIOD": period, "QUANTITY": round(qty, 6)})
        return rows

    def _supply_keys(self, data: dict[str, Any]) -> list[tuple[str, str, str]]:
        keys = {(item, loc, t) for item, loc, _cust, t in data["demand_keys"]}
        keys.update((item, dest, t) for item, _source, dest in data["lanes"] for t in data["periods"])
        keys.update((item, loc, t) for item, loc, _method in data["production_methods"] for t in data["periods"])
        return sorted(keys)

    def _late_keys(self, demand: dict[tuple[str, str, str, str], float], periods: list[str]) -> list[tuple[str, str, str, str, str]]:
        period_index = {period: idx for idx, period in enumerate(periods)}
        keys = []
        for item, loc, cust, req_t in demand:
            req_idx = period_index[req_t]
            max_idx = len(periods) if self.max_late_periods is None else min(len(periods), req_idx + self.max_late_periods + 1)
            for ship_t in periods[req_idx + 1:max_idx]:
                keys.append((item, loc, cust, req_t, ship_t))
        return keys

    def _planning_periods(self, demand_periods: list[str]) -> list[str]:
        dated = sorted(pd.to_datetime(period, errors="coerce") for period in demand_periods)
        dated = [period for period in dated if pd.notna(period)]
        if not dated:
            return sorted(demand_periods)
        start = dated[0].date()
        end = dated[-1].date()
        if self.max_late_periods:
            end = end + timedelta(days=self.max_late_periods)
        days = (end - start).days
        return [(start + timedelta(days=offset)).isoformat() for offset in range(days + 1)]

    def _period_lag(self, req_t: str, ship_t: str) -> int:
        req_idx = self.data["period_index"][req_t]
        ship_idx = self.data["period_index"][ship_t]
        return max(ship_idx - req_idx, 0)

    def _table(self, table_name: str) -> pd.DataFrame:
        exists = self.conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE lower(table_name) = ?", [table_name.lower()]).fetchone()[0]
        if not exists:
            return pd.DataFrame()
        df = self.conn.execute(f'SELECT * FROM "{table_name}"').fetchdf()
        df.columns = [_normalize_column_name(column) for column in df.columns]
        return df

    def _production_methods(self, df: pd.DataFrame) -> list[tuple[str, str, str]]:
        if df.empty:
            return []
        return sorted({(_text(row.get("ITEM")), _text(row.get("LOC")), _text(row.get("METHOD") or row.get("PRODUCTIONMETHOD"))) for row in df.to_dict(orient="records") if _text(row.get("ITEM")) and _text(row.get("LOC")) and _text(row.get("METHOD") or row.get("PRODUCTIONMETHOD"))})

    def _production_steps(self, df: pd.DataFrame) -> dict[tuple[str, str, str], list[tuple[str, float]]]:
        result: dict[tuple[str, str, str], list[tuple[str, float]]] = defaultdict(list)
        if df.empty:
            return result
        for row in df.to_dict(orient="records"):
            item = _text(row.get("ITEM"))
            loc = _text(row.get("LOC"))
            method = _text(row.get("METHOD") or row.get("PRODUCTIONMETHOD"))
            resource = _text(row.get("RESOURCE") or row.get("RES"))
            if item and loc and method and resource:
                result[(item, loc, method)].append((resource, max(_float(row.get("RUN_TIME") or row.get("PRODDUR"), 0.0), 0.0)))
        return result

    def _resource_capacity(self, df: pd.DataFrame, periods: list[str]) -> dict[tuple[str, str, str], float]:
        result = {}
        if df.empty:
            return result
        for row in df.to_dict(orient="records"):
            resource = _text(row.get("RESOURCE") or row.get("RES"))
            loc = _text(row.get("LOC"))
            if resource and loc:
                capacity = _float(row.get("CAPACITY"), DEFAULT_RESOURCE_CAPACITY)
                efficiency = _float(row.get("EFFICIENCY"), 1.0)
                for period in periods:
                    result[(resource, loc, period)] = max(capacity * efficiency, 0.0)
        return result

    def _bom_links(self, df: pd.DataFrame) -> dict[tuple[str, str], list[tuple[str, float]]]:
        result: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
        if df.empty:
            return result
        for row in df.to_dict(orient="records"):
            parent = _text(row.get("PARENT_ITEM") or row.get("ITEM"))
            component = _text(row.get("COMPONENT_ITEM") or row.get("SUBORD"))
            loc = _text(row.get("LOC"))
            if parent and component and loc:
                result[(parent, loc)].append((component, max(_float(row.get("QUANTITY_PER") or row.get("DRAWQTY"), 0.0), 0.0)))
        return result

    def _priority_weight(self, priority: Any) -> float:
        priority_value = max(_float(priority, 999.0), 1.0)
        return 1.0 / priority_value


def run_demand_pegging_optimization(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> dict[str, Any]:
    return DemandPeggingEngine(conn, **kwargs).run()


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


def _period(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None and not pd.isna(value) else ""
    dayfirst = not bool(len(text) >= 10 and text[4] == "-" and text[7] == "-")
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=dayfirst)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _text(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _float(value: Any, default: float) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 1e-9:
        return 0.0
    return round((numerator / denominator) * 100.0, 6)