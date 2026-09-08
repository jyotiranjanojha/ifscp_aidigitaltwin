from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

import pandas as pd
import pyomo.environ as pyo


CAPACITY_CONSTRAINED = "CAPACITY_CONSTRAINED"
MATERIAL_CONSTRAINED = "MATERIAL_CONSTRAINED"
SOURCING_CONSTRAINED = "SOURCING_CONSTRAINED"
LEAD_TIME_CONSTRAINED = "LEAD_TIME_CONSTRAINED"
UNKNOWN_CONSTRAINED = "UNKNOWN_CONSTRAINED"


@dataclass(frozen=True)
class BottleneckDiagnostic:
    order_id: str
    item: str
    customer: str
    unmet_qty: float
    root_cause: str
    bottleneck_entity: str
    suggested_mitigation: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def trace_bottlenecks(
    model: pyo.ConcreteModel,
    model_data: Optional[dict[str, Any]] = None,
    network_df: Optional[pd.DataFrame] = None,
    purchmethod_df: Optional[pd.DataFrame] = None,
    tolerance: float = 1e-6,
) -> list[dict[str, Any]]:
    """Trace root-cause diagnostics for positive UnmetDemand and LateDemand variables."""
    model_data = model_data or {}
    diagnostics = []

    for item, loc, customer, req_t, quantity in _positive_unmet(model, tolerance):
        diagnostics.append(
            _classify_issue(
                model=model,
                model_data=model_data,
                item=item,
                loc=loc,
                customer=customer,
                req_t=req_t,
                ship_t=None,
                quantity=quantity,
                network_df=network_df,
                purchmethod_df=purchmethod_df,
                tolerance=tolerance,
            ).to_dict()
        )

    for item, loc, customer, req_t, ship_t, quantity in _positive_late(model, tolerance):
        diagnostics.append(
            _classify_issue(
                model=model,
                model_data=model_data,
                item=item,
                loc=loc,
                customer=customer,
                req_t=req_t,
                ship_t=ship_t,
                quantity=quantity,
                network_df=network_df,
                purchmethod_df=purchmethod_df,
                tolerance=tolerance,
            ).to_dict()
        )

    return diagnostics


def _classify_issue(
    model: pyo.ConcreteModel,
    model_data: dict[str, Any],
    item: str,
    loc: str,
    customer: str,
    req_t: str,
    ship_t: Optional[str],
    quantity: float,
    network_df: Optional[pd.DataFrame],
    purchmethod_df: Optional[pd.DataFrame],
    tolerance: float,
) -> BottleneckDiagnostic:
    order_id = f"{item}|{loc}|{customer}|{req_t}"

    lead_time = _lead_time_issue(item, loc, req_t, ship_t, model_data, network_df, purchmethod_df)
    if lead_time:
        return BottleneckDiagnostic(order_id, item, customer, quantity, LEAD_TIME_CONSTRAINED, lead_time, "Move order earlier, reduce lead time, or use an alternate lane/supplier.")

    material = _material_issue(item, loc, model_data, tolerance)
    if material:
        return BottleneckDiagnostic(order_id, item, customer, quantity, MATERIAL_CONSTRAINED, material, "Expedite component supply, approve substitutes, or relax BOM effectivity/yield assumptions.")

    capacity = _capacity_issue(model, item, loc, req_t, ship_t, tolerance)
    if capacity:
        return BottleneckDiagnostic(order_id, item, customer, quantity, CAPACITY_CONSTRAINED, capacity, "Increase resource capacity, add overtime/alternate resource, or move demand to a later bucket.")

    sourcing = _sourcing_issue(model, model_data, item, loc, req_t, ship_t, tolerance)
    if sourcing:
        return BottleneckDiagnostic(order_id, item, customer, quantity, SOURCING_CONSTRAINED, sourcing, "Increase lane capacity, enable alternate sourcing, or rebalance demand to another destination.")

    return BottleneckDiagnostic(order_id, item, customer, quantity, UNKNOWN_CONSTRAINED, f"{item}@{loc}", "Inspect active constraints and input data for missing supply, calendar, or policy limits.")


def _positive_unmet(model: pyo.ConcreteModel, tolerance: float) -> Iterable[tuple[str, str, str, str, float]]:
    component = getattr(model, "UnmetDemand", None)
    if component is None:
        return []
    rows = []
    for key in component:
        value = pyo.value(component[key], exception=False) or 0.0
        if value > tolerance:
            item, loc, customer, req_t = key
            rows.append((str(item), str(loc), str(customer), str(req_t), float(value)))
    return rows


def _positive_late(model: pyo.ConcreteModel, tolerance: float) -> Iterable[tuple[str, str, str, str, str, float]]:
    component = getattr(model, "LateDemand", None)
    if component is None:
        return []
    rows = []
    for key in component:
        value = pyo.value(component[key], exception=False) or 0.0
        if value > tolerance:
            item, loc, customer, req_t, ship_t = key
            rows.append((str(item), str(loc), str(customer), str(req_t), str(ship_t), float(value)))
    return rows


def _capacity_issue(model: pyo.ConcreteModel, item: str, loc: str, req_t: str, ship_t: Optional[str], tolerance: float) -> Optional[str]:
    resource_constraints = getattr(model, "ResourceCapacity", None) or getattr(model, "resource_capacity_constraint", None)
    if resource_constraints is None:
        return None

    target_periods = {req_t}
    if ship_t:
        target_periods.add(ship_t)
    for key in resource_constraints:
        period = str(key[-1]) if isinstance(key, tuple) and len(key) >= 3 else req_t
        if period not in target_periods and period > req_t:
            continue
        constraint = resource_constraints[key]
        if _is_binding_upper(constraint, tolerance):
            if isinstance(key, tuple) and len(key) >= 2:
                return f"RES={key[0]}, LOC={key[1]}, PERIOD={period}"
            return str(key)
    return None


def _material_issue(item: str, loc: str, model_data: dict[str, Any], tolerance: float) -> Optional[str]:
    bom_links = model_data.get("bom_links", {})
    inventory = model_data.get("inventory", {})
    for component, qty_per in bom_links.get((item, loc), []):
        available = inventory.get((component, loc), 0.0)
        if qty_per > 0 and available <= tolerance:
            return f"SUBITEM={component}, LOC={loc}, AVAILABLE={available}"
    return None


def _sourcing_issue(
    model: pyo.ConcreteModel,
    model_data: dict[str, Any],
    item: str,
    loc: str,
    req_t: str,
    ship_t: Optional[str],
    tolerance: float,
) -> Optional[str]:
    lane_constraints = getattr(model, "LaneCapacity", None) or getattr(model, "capacity_constraint", None)
    target_periods = {req_t}
    if ship_t:
        target_periods.add(ship_t)

    if lane_constraints is not None:
        for key in lane_constraints:
            key_tuple = key if isinstance(key, tuple) else (key,)
            if len(key_tuple) >= 3 and str(key_tuple[0]) == item and str(key_tuple[2]) == loc:
                period = str(key_tuple[3]) if len(key_tuple) > 3 else req_t
                if period not in target_periods and period > req_t:
                    continue
                if _is_binding_upper(lane_constraints[key], tolerance):
                    limit = model_data.get("lane_capacity", {}).get(key_tuple, "capacity limit")
                    return f"SOURCE={key_tuple[1]}, DEST={key_tuple[2]}, ITEM={key_tuple[0]}, LIMIT={limit}"

    for lane in model_data.get("lanes", []):
        if len(lane) >= 3 and str(lane[0]) == item and str(lane[2]) == loc:
            return f"SOURCE={lane[1]}, DEST={lane[2]}, ITEM={lane[0]}, LIMIT={model_data.get('lane_capacity', {}).get((lane[0], lane[1], lane[2], req_t), 'unknown')}"
    return None


def _lead_time_issue(
    item: str,
    loc: str,
    req_t: str,
    ship_t: Optional[str],
    model_data: dict[str, Any],
    network_df: Optional[pd.DataFrame],
    purchmethod_df: Optional[pd.DataFrame],
) -> Optional[str]:
    period_index = model_data.get("period_index", {})
    if ship_t and req_t in period_index and ship_t in period_index and period_index[ship_t] > period_index[req_t]:
        required_lag = period_index[ship_t] - period_index[req_t]
        lead_time = _lookup_lead_time(item, loc, network_df, purchmethod_df)
        if lead_time and required_lag < lead_time:
            return f"ITEM={item}, LOC={loc}, REQUIRED_LEAD_TIME={lead_time}, AVAILABLE_BUCKETS={required_lag}"

    lead_time = _lookup_lead_time(item, loc, network_df, purchmethod_df)
    if lead_time and not ship_t:
        return f"ITEM={item}, LOC={loc}, REQUIRED_LEAD_TIME={lead_time}"
    return None


def _lookup_lead_time(item: str, loc: str, network_df: Optional[pd.DataFrame], purchmethod_df: Optional[pd.DataFrame]) -> float:
    if network_df is not None and not network_df.empty:
        df = _normalized_df(network_df)
        for row in df.to_dict(orient="records"):
            if _text(row.get("DEST")) == loc:
                lead = _float(row.get("TRANSLEADTIME") or row.get("LEAD_TIME") or row.get("LEADTIME"), 0.0)
                if lead > 0:
                    return lead

    if purchmethod_df is not None and not purchmethod_df.empty:
        df = _normalized_df(purchmethod_df)
        for row in df.to_dict(orient="records"):
            if _text(row.get("ITEM")) == item and _text(row.get("LOC")) == loc:
                lead = _float(row.get("LEADTIME") or row.get("LEAD_TIME"), 0.0)
                if lead > 0:
                    return lead
    return 0.0


def _is_binding_upper(constraint: Any, tolerance: float) -> bool:
    upper = getattr(constraint, "upper", None)
    body = getattr(constraint, "body", None)
    if upper is None or body is None:
        return False
    upper_value = pyo.value(upper, exception=False)
    body_value = pyo.value(body, exception=False)
    if upper_value is None or body_value is None:
        return False
    return abs(float(upper_value) - float(body_value)) <= tolerance


def _normalized_df(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper() for column in normalized.columns]
    return normalized


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