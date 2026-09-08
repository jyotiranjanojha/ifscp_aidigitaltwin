from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, DefaultDict, Iterable, Literal, Optional

import duckdb
import pandas as pd
import polars as pl


PlanningStatus = Literal["MET", "LATE_MET", "UNMET"]


@dataclass(frozen=True)
class DemandLine:
    order_id: str
    item: str
    customer: str
    cust_loc: str
    req_date: date
    req_qty: float
    priority: int
    order_type: str


@dataclass(frozen=True)
class LaneOption:
    item: str
    source: str
    dest: str
    priority: int
    base_cost: float
    transit_days: int


@dataclass(frozen=True)
class ResourceStep:
    resource: str
    loc: str
    hours_per_unit: float


@dataclass(frozen=True)
class FeasibilityResult:
    feasible: bool
    bottleneck_reason: str = ""


class HeuristicSupplyPlanningEngine:
    """Sequential priority-based supply planning and pegging over DuckDB BY tables."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        horizon_days: int = 365,
        inventory_holding_cost_per_unit_day: float = 0.0,
        late_penalty_per_unit_day: float = 1.0,
        production_cost_per_resource_hour: float = 0.1,
    ) -> None:
        self.conn = conn
        self.horizon_days = horizon_days
        self.inventory_holding_cost_per_unit_day = inventory_holding_cost_per_unit_day
        self.late_penalty_per_unit_day = late_penalty_per_unit_day
        self.production_cost_per_resource_hour = production_cost_per_resource_hour

        self.tables: dict[str, pl.DataFrame] = {}
        self.inventory_state: DefaultDict[tuple[str, str], float] = defaultdict(float)
        self.resource_capacity: DefaultDict[tuple[str, str, date], float] = defaultdict(float)
        self.initial_resource_capacity: DefaultDict[tuple[str, str, date], float] = defaultdict(float)
        self.lane_capacity: DefaultDict[tuple[str, str, str, date], float] = defaultdict(float)
        self.initial_lane_capacity: DefaultDict[tuple[str, str, str, date], float] = defaultdict(float)
        self.lane_flows: DefaultDict[tuple[str, str, str, date], float] = defaultdict(float)
        self.resource_usage: DefaultDict[tuple[str, str, date], float] = defaultdict(float)

        self.lanes_by_item_dest: DefaultDict[tuple[str, str], list[LaneOption]] = defaultdict(list)
        self.resource_steps_by_item_loc: DefaultDict[tuple[str, str], list[ResourceStep]] = defaultdict(list)
        self.bom_by_item_loc: DefaultDict[tuple[str, str], list[tuple[str, str, float]]] = defaultdict(list)
        self.demand_qty_by_order: dict[str, float] = {}
        self.periods: list[date] = []

    def run(self) -> dict[str, Any]:
        start_time = time.perf_counter()
        self._load_tables()
        demand_lines = self._build_demand_lines()
        self.demand_qty_by_order = {line.order_id: line.req_qty for line in demand_lines}
        self._initialize_periods(demand_lines)
        self._initialize_inventory_state()
        self._initialize_resource_capacity()
        self._initialize_sourcing_lanes()
        self._initialize_production_and_bom()

        pegging_records: list[dict[str, Any]] = []
        for demand in demand_lines:
            pegging_records.append(self._peg_demand(demand))

        solve_time = time.perf_counter() - start_time
        summary = self._build_summary(pegging_records, solve_time)
        return {
            "status": self._overall_status(pegging_records),
            "method": "duckdb_polars_priority_heuristic",
            "summary": summary,
            "pegging_records": pegging_records,
            "resource_utilization": self._build_resource_utilization(),
            "lane_flows": self._build_lane_flows(),
            "shipments": self._build_shipments(),
            "production": [],
            "total_cost": summary["total_cost"],
            "solve_time_ms": round(solve_time * 1000, 3),
        }

    def _load_tables(self) -> None:
        for table_name in self._list_tables():
            pdf = self.conn.execute(f'SELECT * FROM "{table_name}"').fetchdf()
            pdf.columns = [str(col).strip().upper() for col in pdf.columns]
            self.tables[table_name.lower()] = pl.DataFrame(pdf.to_dict(orient="list"))

    def _list_tables(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            """
        ).fetchall()
        return [str(row[0]) for row in rows]

    def _table(self, name: str) -> pl.DataFrame:
        return self.tables.get(name.lower(), pl.DataFrame())

    def _build_demand_lines(self) -> list[DemandLine]:
        rows: list[dict[str, Any]] = []
        rows.extend(self._customer_order_rows())
        rows.extend(self._forecast_rows())
        if not rows:
            return []

        demands = pl.DataFrame(rows).with_columns(
            pl.col("REQ_DATE").cast(pl.Date),
            pl.col("REQ_QTY").cast(pl.Float64),
            pl.col("PRIORITY").cast(pl.Int64),
        )
        demands = demands.sort(
            by=["ORDER_RANK", "PRIORITY", "REQ_DATE", "REQ_QTY"],
            descending=[False, False, False, True],
        )
        return [
            DemandLine(
                order_id=str(row["ORDER_ID"]),
                item=str(row["ITEM"]),
                customer=str(row["CUSTOMER"]),
                cust_loc=str(row["CUST_LOC"]),
                req_date=row["REQ_DATE"],
                req_qty=float(row["REQ_QTY"]),
                priority=int(row["PRIORITY"]),
                order_type=str(row["ORDER_TYPE"]),
            )
            for row in demands.iter_rows(named=True)
            if float(row["REQ_QTY"]) > 0
        ]

    def _customer_order_rows(self) -> list[dict[str, Any]]:
        df = self._table("customerorder")
        if df.is_empty():
            return []

        rows = []
        for idx, row in enumerate(df.iter_rows(named=True), start=1):
            item = self._value(row, "ITEM")
            loc = self._value(row, "LOC", "DEST", "SHIPTO", "CUSTOMERLOC")
            qty = self._float_value(row, "QUANTITY", "QTY", "ORDERQTY", default=0.0)
            if not item or not loc or qty <= 0:
                continue
            req_date = self._date_value(row, "REQUESTED_DATE", "REQ_DATE", "SHIPDATE", "DUE_DATE", "ORDER_DATE")
            rows.append({
                "ORDER_ID": self._value(row, "ORDER_ID", "ORDERID", "CUSTOMERORDER", default=f"CO-{idx}"),
                "ITEM": item,
                "CUSTOMER": self._value(row, "CUSTOMER", "CUST", default=loc),
                "CUST_LOC": loc,
                "REQ_DATE": req_date,
                "REQ_QTY": qty,
                "PRIORITY": self._int_value(row, "PRIORITY", default=1),
                "ORDER_TYPE": "CUSTOMER_ORDER",
                "ORDER_RANK": 0,
            })
        return rows

    def _forecast_rows(self) -> list[dict[str, Any]]:
        df = self._table("dfutoskufcst")
        if df.is_empty():
            return []

        rows = []
        for idx, row in enumerate(df.iter_rows(named=True), start=1):
            item = self._value(row, "ITEM")
            loc = self._value(row, "LOC", "DEST")
            qty = self._float_value(row, "QUANTITY", "QTY", "FCST_QTY", default=0.0)
            if not item or not loc or qty <= 0:
                continue
            req_date = self._date_value(row, "FCST_DATE", "SHIPDATE", "DUE_DATE", "REQ_DATE")
            rows.append({
                "ORDER_ID": self._value(row, "ORDER_ID", "FCST_ID", default=f"FCST-{idx}"),
                "ITEM": item,
                "CUSTOMER": self._value(row, "CUSTOMER", "CUST", default=loc),
                "CUST_LOC": loc,
                "REQ_DATE": req_date,
                "REQ_QTY": qty,
                "PRIORITY": self._int_value(row, "PRIORITY", default=999),
                "ORDER_TYPE": "FORECAST",
                "ORDER_RANK": 1,
            })
        return rows

    def _initialize_periods(self, demand_lines: list[DemandLine]) -> None:
        if demand_lines:
            start_period = min(line.req_date for line in demand_lines) - timedelta(days=self.horizon_days)
            end_period = max(line.req_date for line in demand_lines) + timedelta(days=self.horizon_days)
        else:
            start_period = date.today()
            end_period = start_period + timedelta(days=self.horizon_days)
        self.periods = [start_period + timedelta(days=offset) for offset in range((end_period - start_period).days + 1)]

    def _initialize_inventory_state(self) -> None:
        for row in self._table("inventory").iter_rows(named=True):
            item = self._value(row, "ITEM")
            loc = self._value(row, "LOC")
            if not item or not loc:
                continue
            on_hand = self._float_value(row, "ON_HAND", "QTY", "QUANTITY", default=0.0)
            on_order = self._float_value(row, "ON_ORDER", default=0.0)
            allocated = self._float_value(row, "ALLOCATED", default=0.0)
            self.inventory_state[(item, loc)] += max(on_hand + on_order - allocated, 0.0)

        for row in self._table("schedrcpts").iter_rows(named=True):
            item = self._value(row, "ITEM")
            loc = self._value(row, "LOC")
            if item and loc:
                self.inventory_state[(item, loc)] += self._float_value(row, "QUANTITY", "QTY", default=0.0)

    def _initialize_resource_capacity(self) -> None:
        for row in self._table("res").iter_rows(named=True):
            resource = self._value(row, "RESOURCE", "RES")
            loc = self._value(row, "LOC")
            if not resource or not loc:
                continue
            base_capacity = self._float_value(row, "CAPACITY", "AVAILABILITY", default=24.0)
            efficiency = self._float_value(row, "EFFICIENCY", default=1.0)
            capacity = max(base_capacity * efficiency, 0.0)
            for period in self.periods:
                period_capacity = capacity if self._is_working_period(row, period) else 0.0
                key = (resource, loc, period)
                self.resource_capacity[key] += period_capacity
                self.initial_resource_capacity[key] += period_capacity

    def _initialize_sourcing_lanes(self) -> None:
        valid_network_pairs = self._network_pairs()
        for row in self._table("sourcing").iter_rows(named=True):
            item = self._value(row, "ITEM")
            source = self._value(row, "SOURCE", "SRC")
            dest = self._value(row, "DEST", "LOC")
            if not item or not source or not dest:
                continue
            if valid_network_pairs and (source, dest) not in valid_network_pairs:
                continue

            capacity = self._float_value(row, "MAX_CAPACITY", "CAPACITY", default=math.inf)
            base_cost = self._float_value(row, "BASE_COST", "COST", "UNIT_COST", default=0.0)
            transit_days = max(self._int_value(row, "TRANSITTIME", "TRANSPORT_TIME", "LEAD_TIME", default=0), 0)
            priority = self._int_value(row, "PRIORITY", default=999)
            option = LaneOption(item=item, source=source, dest=dest, priority=priority, base_cost=base_cost, transit_days=transit_days)
            self.lanes_by_item_dest[(item, dest)].append(option)

            for period in self.periods:
                key = (source, dest, item, period)
                self.lane_capacity[key] += capacity
                self.initial_lane_capacity[key] += capacity

        for lane_options in self.lanes_by_item_dest.values():
            lane_options.sort(key=lambda lane: (lane.priority, lane.base_cost))

    def _network_pairs(self) -> set[tuple[str, str]]:
        network = self._table("network")
        if network.is_empty():
            return set()
        pairs = set()
        for row in network.iter_rows(named=True):
            source = self._value(row, "SOURCE", "SRC")
            dest = self._value(row, "DEST", "LOC")
            if source and dest:
                pairs.add((source, dest))
        return pairs

    def _initialize_production_and_bom(self) -> None:
        for row in self._table("productionstep").iter_rows(named=True):
            item = self._value(row, "ITEM")
            loc = self._value(row, "LOC")
            resource = self._value(row, "RESOURCE", "RES")
            if not item or not loc or not resource:
                continue
            hours_per_unit = sum(
                self._float_value(row, col, default=0.0)
                for col in ("SETUP_TIME", "RUN_TIME", "QUEUE_TIME", "MOVE_TIME")
            )
            self.resource_steps_by_item_loc[(item, loc)].append(ResourceStep(resource, loc, max(hours_per_unit, 0.0)))

        for row in self._table("billofmaterials").iter_rows(named=True):
            parent = self._value(row, "PARENT_ITEM", "ITEM")
            component = self._value(row, "COMPONENT_ITEM", "SUBITEM", "COMPONENT")
            loc = self._value(row, "LOC")
            if not parent or not component or not loc:
                continue
            qty_per = self._float_value(row, "QUANTITY_PER", "QTY_PER", "USAGE", default=1.0)
            scrap = self._float_value(row, "SCRAP_FACTOR", default=0.0)
            self.bom_by_item_loc[(parent, loc)].append((component, loc, qty_per * (1.0 + scrap)))

    def _peg_demand(self, demand: DemandLine) -> dict[str, Any]:
        allocated_from_inventory = min(self.inventory_state[(demand.item, demand.cust_loc)], demand.req_qty)
        self.inventory_state[(demand.item, demand.cust_loc)] -= allocated_from_inventory
        remaining_qty = demand.req_qty - allocated_from_inventory
        source_used = "ON_HAND" if allocated_from_inventory > 0 else None

        if remaining_qty <= 1e-9:
            return self._pegging_record(demand, demand.req_date, "MET", 0, demand.req_qty, source_used, [], "")

        backward = self._find_feasible_supply(demand.item, demand.cust_loc, demand.req_date, remaining_qty, backward=True)
        if backward:
            self._commit_supply(backward, remaining_qty)
            return self._pegging_record(
                demand, demand.req_date, "MET", 0, demand.req_qty, backward.source, backward.resources, ""
            )

        forward_result = self._find_forward_supply(demand, remaining_qty)
        if forward_result:
            schedule_date, lane = forward_result
            self._commit_supply(lane, remaining_qty)
            delay_days = max((schedule_date - demand.req_date).days, 0)
            return self._pegging_record(
                demand, schedule_date, "LATE_MET", delay_days, demand.req_qty, lane.source, lane.resources, ""
            )

        bottleneck = self._diagnose_bottleneck(demand.item, demand.cust_loc, demand.req_date, remaining_qty)
        allocated_qty = allocated_from_inventory
        return self._pegging_record(demand, None, "UNMET", 0, allocated_qty, source_used, [], bottleneck)

    def _find_forward_supply(self, demand: DemandLine, qty: float) -> Optional[tuple[date, Any]]:
        start_idx = self._period_index(demand.req_date) + 1
        for ship_period in self.periods[start_idx:]:
            feasible = self._find_feasible_supply(demand.item, demand.cust_loc, ship_period, qty, backward=False)
            if feasible:
                return ship_period, feasible
        return None

    def _find_feasible_supply(self, item: str, dest: str, req_period: date, qty: float, backward: bool) -> Optional[Any]:
        for lane in self.lanes_by_item_dest.get((item, dest), []):
            dispatch_period = req_period - timedelta(days=lane.transit_days)
            if dispatch_period not in self.periods:
                continue
            resource_period = dispatch_period
            feasibility = self._check_lane(lane, dispatch_period, qty)
            if not feasibility.feasible:
                continue
            feasibility = self._check_resources(item, lane.source, resource_period, qty)
            if not feasibility.feasible:
                continue
            feasibility = self._check_bom(item, lane.source, qty)
            if not feasibility.feasible:
                continue
            return type("CommittedLane", (), {
                "lane": lane,
                "source": lane.source,
                "dest": lane.dest,
                "item": lane.item,
                "dispatch_period": dispatch_period,
                "resource_period": resource_period,
                "resources": [step.resource for step in self.resource_steps_by_item_loc.get((item, lane.source), [])],
            })()
        return None

    def _check_lane(self, lane: LaneOption, period: date, qty: float) -> FeasibilityResult:
        available = self.lane_capacity[(lane.source, lane.dest, lane.item, period)]
        if available + 1e-9 < qty:
            return FeasibilityResult(False, f"Sourcing lane {lane.source}->{lane.dest} capacity exceeded")
        return FeasibilityResult(True)

    def _check_resources(self, item: str, loc: str, period: date, qty: float) -> FeasibilityResult:
        for step in self.resource_steps_by_item_loc.get((item, loc), []):
            required = step.hours_per_unit * qty
            if self.resource_capacity[(step.resource, step.loc, period)] + 1e-9 < required:
                return FeasibilityResult(False, f"Resource {step.resource} capacity exceeded")
        return FeasibilityResult(True)

    def _check_bom(self, item: str, loc: str, qty: float) -> FeasibilityResult:
        for component, component_loc, qty_per in self.bom_by_item_loc.get((item, loc), []):
            required = qty * qty_per
            if self.inventory_state[(component, component_loc)] + 1e-9 < required:
                return FeasibilityResult(False, f"Starved by component {component}")
        return FeasibilityResult(True)

    def _commit_supply(self, committed: Any, qty: float) -> None:
        lane = committed.lane
        lane_key = (lane.source, lane.dest, lane.item, committed.dispatch_period)
        self.lane_capacity[lane_key] -= qty
        self.lane_flows[lane_key] += qty

        for step in self.resource_steps_by_item_loc.get((lane.item, lane.source), []):
            used = step.hours_per_unit * qty
            res_key = (step.resource, step.loc, committed.resource_period)
            self.resource_capacity[res_key] -= used
            self.resource_usage[res_key] += used

        for component, component_loc, qty_per in self.bom_by_item_loc.get((lane.item, lane.source), []):
            self.inventory_state[(component, component_loc)] -= qty * qty_per

    def _diagnose_bottleneck(self, item: str, dest: str, req_period: date, qty: float) -> str:
        lanes = self.lanes_by_item_dest.get((item, dest), [])
        if not lanes:
            return f"No valid sourcing lane for {item} to {dest}"
        for lane in lanes:
            period = req_period - timedelta(days=lane.transit_days)
            if period not in self.periods:
                return f"Required dispatch date outside planning horizon for lane {lane.source}->{lane.dest}"
            for check in (
                self._check_lane(lane, period, qty),
                self._check_resources(item, lane.source, period, qty),
                self._check_bom(item, lane.source, qty),
            ):
                if not check.feasible:
                    return check.bottleneck_reason
        return "No feasible simultaneous capacity/material bucket found"

    def _pegging_record(
        self,
        demand: DemandLine,
        ship_date: Optional[date],
        status: PlanningStatus,
        delay_days: int,
        allocated_qty: float,
        source_used: Optional[str],
        res_used: Iterable[str],
        bottleneck_reason: str,
    ) -> dict[str, Any]:
        return {
            "order_id": demand.order_id,
            "item": demand.item,
            "customer": demand.customer,
            "req_date": demand.req_date.isoformat(),
            "ship_date": ship_date.isoformat() if ship_date else None,
            "status": status,
            "delay_days": delay_days,
            "allocated_qty": round(float(allocated_qty), 6),
            "source_used": source_used,
            "res_used": sorted(set(res_used)),
            "bottleneck_reason": bottleneck_reason,
        }

    def _build_summary(self, records: list[dict[str, Any]], solve_time: float) -> dict[str, float]:
        total_demand_qty = sum(self.demand_qty_by_order.get(record["order_id"], 0.0) for record in records)
        met_qty = sum(record["allocated_qty"] for record in records if record["status"] == "MET")
        late_qty = sum(record["allocated_qty"] for record in records if record["status"] == "LATE_MET")
        unmet_qty = max(total_demand_qty - met_qty - late_qty, 0.0)
        late_delays = [record["delay_days"] for record in records if record["status"] == "LATE_MET"]
        total_cost = self._calculate_total_cost(records)
        return {
            "total_demand_qty": round(total_demand_qty, 6),
            "met_qty": round(met_qty, 6),
            "met_pct": self._pct(met_qty, total_demand_qty),
            "late_qty": round(late_qty, 6),
            "late_pct": self._pct(late_qty, total_demand_qty),
            "avg_delay_days": round(sum(late_delays) / len(late_delays), 6) if late_delays else 0.0,
            "unmet_qty": round(unmet_qty, 6),
            "unmet_pct": self._pct(unmet_qty, total_demand_qty),
            "total_cost": round(total_cost, 6),
            "solve_time_seconds": round(solve_time, 6),
        }

    def _calculate_total_cost(self, records: list[dict[str, Any]]) -> float:
        lane_cost = 0.0
        for (source, dest, item, _period), qty in self.lane_flows.items():
            lane_cost += qty * self._lane_base_cost(item, source, dest)
        production_cost = sum(self.resource_usage.values()) * self.production_cost_per_resource_hour
        late_cost = sum(record["allocated_qty"] * record["delay_days"] for record in records) * self.late_penalty_per_unit_day
        holding_cost = sum(max(qty, 0.0) for qty in self.inventory_state.values()) * self.inventory_holding_cost_per_unit_day
        return lane_cost + production_cost + late_cost + holding_cost

    def _build_resource_utilization(self) -> list[dict[str, Any]]:
        rows = []
        for key, initial in sorted(self.initial_resource_capacity.items()):
            resource, loc, period = key
            used = self.resource_usage.get(key, 0.0)
            rows.append({
                "RES": resource,
                "LOC": loc,
                "PERIOD": period.isoformat(),
                "capacity": round(initial, 6),
                "used_capacity": round(used, 6),
                "utilization_pct": self._pct(used, initial),
            })
        return rows

    def _build_lane_flows(self) -> list[dict[str, Any]]:
        return [
            {
                "SOURCE": source,
                "DEST": dest,
                "ITEM": item,
                "PERIOD": period.isoformat(),
                "quantity": round(qty, 6),
            }
            for (source, dest, item, period), qty in sorted(self.lane_flows.items())
            if qty > 1e-9
        ]

    def _build_shipments(self) -> list[dict[str, Any]]:
        shipments = []
        for (source, dest, item, _period), qty in sorted(self.lane_flows.items()):
            if qty <= 1e-9:
                continue
            cost = qty * self._lane_base_cost(item, source, dest)
            shipments.append({
                "ITEM": item,
                "SOURCE": source,
                "DEST": dest,
                "QUANTITY": round(qty, 2),
                "COST": round(cost, 2),
            })
        return shipments

    def _lane_base_cost(self, item: str, source: str, dest: str) -> float:
        for option in self.lanes_by_item_dest.get((item, dest), []):
            if option.source == source:
                return option.base_cost
        return 0.0

    def _overall_status(self, records: list[dict[str, Any]]) -> str:
        if any(record["status"] == "UNMET" for record in records):
            return "infeasible"
        return "optimal"

    def _is_working_period(self, row: dict[str, Any], period: date) -> bool:
        calendar = self._value(row, "CALENDAR")
        if not calendar:
            return True
        calpattern = self._table("calpattern")
        if calpattern.is_empty():
            return True
        for pattern_row in calpattern.iter_rows(named=True):
            if self._value(pattern_row, "CALENDAR") != calendar:
                continue
            day_of_week = self._optional_int_value(pattern_row, "DAY_OF_WEEK")
            is_working = self._bool_value(pattern_row, "IS_WORKING", default=True)
            if day_of_week is not None and day_of_week == period.isoweekday():
                return is_working
        return True

    def _period_index(self, period: date) -> int:
        try:
            return self.periods.index(period)
        except ValueError:
            return 0

    def _value(self, row: dict[str, Any], *names: str, default: Optional[str] = None) -> Optional[str]:
        for name in names:
            value = row.get(name)
            if value is not None and not self._is_null(value):
                return str(value)
        return default

    def _float_value(self, row: dict[str, Any], *names: str, default: float = 0.0) -> float:
        for name in names:
            value = row.get(name)
            if value is not None and not self._is_null(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return default
        return default

    def _int_value(self, row: dict[str, Any], *names: str, default: int = 0) -> int:
        value = self._float_value(row, *names, default=float(default))
        return int(value)

    def _optional_int_value(self, row: dict[str, Any], *names: str) -> Optional[int]:
        for name in names:
            value = row.get(name)
            if value is not None and not self._is_null(value):
                return int(float(value))
        return None

    def _bool_value(self, row: dict[str, Any], *names: str, default: bool = True) -> bool:
        for name in names:
            value = row.get(name)
            if value is None or self._is_null(value):
                continue
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            return str(value).strip().lower() in {"1", "true", "yes", "y"}
        return default

    def _date_value(self, row: dict[str, Any], *names: str) -> date:
        for name in names:
            value = row.get(name)
            if value is not None and not self._is_null(value):
                if isinstance(value, datetime):
                    return value.date()
                if isinstance(value, date):
                    return value
                parsed = pd.to_datetime(value, errors="coerce")
                if pd.notna(parsed):
                    return parsed.date()
        return date.today()

    def _is_null(self, value: Any) -> bool:
        try:
            return bool(pd.isna(value))
        except ValueError:
            return False

    def _pct(self, numerator: float, denominator: float) -> float:
        if denominator <= 1e-9:
            return 0.0
        return round((numerator / denominator) * 100.0, 6)


def run_heuristic_supply_planning(
    conn: duckdb.DuckDBPyConnection,
    horizon_days: int = 365,
    **kwargs: Any,
) -> dict[str, Any]:
    engine = HeuristicSupplyPlanningEngine(conn, horizon_days=horizon_days, **kwargs)
    return engine.run()