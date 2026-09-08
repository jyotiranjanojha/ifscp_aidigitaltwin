from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import duckdb
import pandas as pd

from app.optimization.demand_engine import run_demand_pegging_optimization


MitigationType = Literal[
    "OVERTIME_AUTHORIZATION",
    "EXPEDITE_SOURCING",
    "ACTIVATE_ALT_BOM",
    "SUPERSESSION_OVERRIDE",
]


@dataclass(frozen=True)
class MitigationAction:
    action_type: MitigationType
    target: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""


MITIGATION_ACTION_TEMPLATES: dict[MitigationType, dict[str, Any]] = {
    "OVERTIME_AUTHORIZATION": {
        "target_keys": ["RES", "LOC", "PERIOD"],
        "parameters": ["capacity_increase_pct", "capacity_increase_hours", "incremental_hourly_cost"],
        "description": "Temporarily increase resource capacity for a resource/location/time bucket.",
    },
    "EXPEDITE_SOURCING": {
        "target_keys": ["ITEM", "SOURCE", "DEST", "PERIOD"],
        "parameters": ["transit_reduction_days", "capacity_increase_units", "capacity_increase_pct", "freight_surcharge"],
        "description": "Reduce transport/procurement lead time or increase sourcing lane capacity with a freight surcharge.",
    },
    "ACTIVATE_ALT_BOM": {
        "target_keys": ["ITEM", "LOC", "BOMNUM"],
        "parameters": ["force", "allow", "conversion_penalty"],
        "description": "Allow alternate BOM and alternate production-step routes in the what-if solve.",
    },
    "SUPERSESSION_OVERRIDE": {
        "target_keys": ["ITEM", "LOC", "ALTITEM", "DMDGROUP"],
        "parameters": ["force_enable", "conversion_ratio", "substitution_penalty"],
        "description": "Enable approved replacement part rules for constrained components.",
    },
}


class ScenarioRunner:
    def __init__(
        self,
        baseline_data: dict[str, pd.DataFrame],
        mitigation_actions: list[MitigationAction | dict[str, Any]],
        solver_kwargs: Optional[dict[str, Any]] = None,
        parallel: bool = True,
    ) -> None:
        self.baseline_data = _copy_dataframes(baseline_data)
        self.mitigation_actions = [_coerce_action(action) for action in mitigation_actions]
        self.solver_kwargs = solver_kwargs or {}
        self.parallel = parallel

    def run(self) -> dict[str, Any]:
        what_if_data = _copy_dataframes(self.baseline_data)
        applied_changes = self._apply_actions(what_if_data)

        if self.parallel:
            try:
                with ProcessPoolExecutor(max_workers=2) as executor:
                    baseline_future = executor.submit(_solve_dataframe_pack, self.baseline_data, self.solver_kwargs)
                    what_if_future = executor.submit(_solve_dataframe_pack, what_if_data, self.solver_kwargs)
                    baseline_result = baseline_future.result()
                    what_if_result = what_if_future.result()
            except Exception:
                baseline_result = self._solve(self.baseline_data)
                what_if_result = self._solve(what_if_data)
        else:
            baseline_result = self._solve(self.baseline_data)
            what_if_result = self._solve(what_if_data)

        delta_report = self._build_delta_report(baseline_result, what_if_result, applied_changes)
        return {
            "baseline_result": baseline_result,
            "what_if_result": what_if_result,
            "applied_actions": [self._action_summary(action) for action in self.mitigation_actions],
            "applied_changes": applied_changes,
            "delta_report": delta_report,
        }

    def _solve(self, data: dict[str, pd.DataFrame]) -> dict[str, Any]:
        conn = _dataframes_to_duckdb(data)
        return run_demand_pegging_optimization(conn, **self.solver_kwargs)

    def _apply_actions(self, data: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for action in self.mitigation_actions:
            if action.action_type == "OVERTIME_AUTHORIZATION":
                changes.extend(_apply_overtime(data, action))
            elif action.action_type == "EXPEDITE_SOURCING":
                changes.extend(_apply_expedite_sourcing(data, action))
            elif action.action_type == "ACTIVATE_ALT_BOM":
                changes.extend(_apply_alt_bom(data, action))
            elif action.action_type == "SUPERSESSION_OVERRIDE":
                changes.extend(_apply_supersession_override(data, action))
        return changes

    def _build_delta_report(
        self,
        baseline_result: dict[str, Any],
        what_if_result: dict[str, Any],
        applied_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        baseline_summary = baseline_result.get("summary", {})
        what_if_summary = what_if_result.get("summary", {})
        unmet_converted = _number(baseline_summary.get("unmet_qty")) - _number(what_if_summary.get("unmet_qty"))
        met_lift = _number(what_if_summary.get("met_qty")) - _number(baseline_summary.get("met_qty"))
        protected_revenue = _number(baseline_summary.get("revenue_at_risk")) - _number(what_if_summary.get("revenue_at_risk"))
        incremental_solver_cost = _number(what_if_summary.get("total_cost")) - _number(baseline_summary.get("total_cost"))
        mitigation_cost = sum(_number(change.get("incremental_cost")) for change in applied_changes)
        total_incremental_cost = incremental_solver_cost + mitigation_cost

        return {
            "baseline_status": baseline_result.get("status"),
            "what_if_status": what_if_result.get("status"),
            "met_units_delta": round(met_lift, 6),
            "unmet_units_converted": round(unmet_converted, 6),
            "protected_revenue": round(protected_revenue, 6),
            "incremental_solver_cost": round(incremental_solver_cost, 6),
            "mitigation_cost": round(mitigation_cost, 6),
            "total_incremental_cost": round(total_incremental_cost, 6),
            "summary_text": self._summary_text(unmet_converted, protected_revenue, mitigation_cost, total_incremental_cost),
        }

    def _summary_text(self, unmet_converted: float, protected_revenue: float, mitigation_cost: float, total_incremental_cost: float) -> str:
        label = self.mitigation_actions[0].description or self.mitigation_actions[0].action_type.replace("_", " ").title() if self.mitigation_actions else "Mitigation scenario"
        return (
            f"Applying {label} costs ${mitigation_cost:,.0f} and converts "
            f"{max(unmet_converted, 0.0):,.0f} units from Unmet to Met/Late Met, "
            f"protecting ${max(protected_revenue, 0.0):,.0f} in revenue. "
            f"Net objective impact is ${total_incremental_cost:,.0f}."
        )

    def _action_summary(self, action: MitigationAction) -> dict[str, Any]:
        return {
            "action_type": action.action_type,
            "target": action.target,
            "parameters": action.parameters,
            "description": action.description or MITIGATION_ACTION_TEMPLATES[action.action_type]["description"],
        }


def run_mitigation_scenario(
    baseline_data: dict[str, pd.DataFrame],
    mitigation_actions: list[MitigationAction | dict[str, Any]],
    solver_kwargs: Optional[dict[str, Any]] = None,
    parallel: bool = True,
) -> dict[str, Any]:
    return ScenarioRunner(baseline_data, mitigation_actions, solver_kwargs=solver_kwargs, parallel=parallel).run()


def _solve_dataframe_pack(data: dict[str, pd.DataFrame], solver_kwargs: dict[str, Any]) -> dict[str, Any]:
    conn = _dataframes_to_duckdb(data)
    return run_demand_pegging_optimization(conn, **solver_kwargs)


def _apply_overtime(data: dict[str, pd.DataFrame], action: MitigationAction) -> list[dict[str, Any]]:
    res_df = data.get("res")
    if res_df is None or res_df.empty:
        return []
    _ensure_column(res_df, "CAPACITY", 24.0)
    mask = _match(res_df, {"RES": action.target.get("RES"), "LOC": action.target.get("LOC")})
    if not mask.any():
        return []
    old_capacity = pd.to_numeric(res_df.loc[mask, "CAPACITY"], errors="coerce").fillna(24.0)
    increase_hours = _number(action.parameters.get("capacity_increase_hours"))
    increase_pct = _number(action.parameters.get("capacity_increase_pct"))
    if increase_pct:
        increase_hours = old_capacity * increase_pct
    res_df.loc[mask, "CAPACITY"] = old_capacity + increase_hours
    hourly_cost = _number(action.parameters.get("incremental_hourly_cost"))
    return [{"entity": "res", "rows": int(mask.sum()), "column": "CAPACITY", "old_value": float(old_capacity.iloc[0]), "new_value": float(res_df.loc[mask, "CAPACITY"].iloc[0]), "incremental_cost": float(increase_hours.sum() * hourly_cost)}]


def _apply_expedite_sourcing(data: dict[str, pd.DataFrame], action: MitigationAction) -> list[dict[str, Any]]:
    changes = []
    sourcing_df = data.get("sourcing")
    if sourcing_df is not None and not sourcing_df.empty:
        _ensure_column(sourcing_df, "MAX_CAPACITY", pd.NA)
        _ensure_column(sourcing_df, "FACTOR", 1.0)
        mask = _match(sourcing_df, {"ITEM": action.target.get("ITEM"), "SOURCE": action.target.get("SOURCE"), "DEST": action.target.get("DEST")})
        if mask.any():
            if action.parameters.get("capacity_increase_units") is not None:
                units = _number(action.parameters.get("capacity_increase_units"))
                base = pd.to_numeric(sourcing_df.loc[mask, "MAX_CAPACITY"], errors="coerce")
                if base.isna().all():
                    factor = pd.to_numeric(sourcing_df.loc[mask, "FACTOR"], errors="coerce").fillna(1.0)
                    sourcing_df.loc[mask, "FACTOR"] = factor + (units / 1_000_000.0)
                    changes.append({"entity": "sourcing", "rows": int(mask.sum()), "column": "FACTOR", "incremental_cost": units * _number(action.parameters.get("freight_surcharge"))})
                else:
                    sourcing_df.loc[mask, "MAX_CAPACITY"] = base.fillna(0.0) + units
                    changes.append({"entity": "sourcing", "rows": int(mask.sum()), "column": "MAX_CAPACITY", "incremental_cost": units * _number(action.parameters.get("freight_surcharge"))})
            if action.parameters.get("capacity_increase_pct") is not None:
                pct = _number(action.parameters.get("capacity_increase_pct"))
                factor = pd.to_numeric(sourcing_df.loc[mask, "FACTOR"], errors="coerce").fillna(1.0)
                sourcing_df.loc[mask, "FACTOR"] = factor * (1.0 + pct)
                changes.append({"entity": "sourcing", "rows": int(mask.sum()), "column": "FACTOR", "incremental_cost": 0.0})

    network_df = data.get("network")
    if network_df is not None and not network_df.empty and action.parameters.get("transit_reduction_days") is not None:
        _ensure_column(network_df, "TRANSLEADTIME", 0.0)
        mask = _match(network_df, {"SOURCE": action.target.get("SOURCE"), "DEST": action.target.get("DEST")})
        if mask.any():
            old = pd.to_numeric(network_df.loc[mask, "TRANSLEADTIME"], errors="coerce").fillna(0.0)
            network_df.loc[mask, "TRANSLEADTIME"] = (old - _number(action.parameters.get("transit_reduction_days"))).clip(lower=0.0)
            changes.append({"entity": "network", "rows": int(mask.sum()), "column": "TRANSLEADTIME", "incremental_cost": 0.0})
    return changes


def _apply_alt_bom(data: dict[str, pd.DataFrame], action: MitigationAction) -> list[dict[str, Any]]:
    alt_bom = data.get("altbillofmaterials")
    if alt_bom is None or alt_bom.empty:
        return []
    bom = data.get("billofmaterials", pd.DataFrame())
    mask = _match(alt_bom, {"ITEM": action.target.get("ITEM"), "LOC": action.target.get("LOC"), "BOMNUM": action.target.get("BOMNUM")})
    selected = alt_bom.loc[mask].copy()
    if selected.empty:
        return []
    selected["SUBORD"] = selected.get("ALTSUBORD", selected.get("SUBORD"))
    data["billofmaterials"] = pd.concat([bom, selected[bom.columns.intersection(selected.columns)] if not bom.empty else selected], ignore_index=True)
    return [{"entity": "billofmaterials", "rows": len(selected), "column": "ALT_BOM", "incremental_cost": _number(action.parameters.get("conversion_penalty")) * len(selected)}]


def _apply_supersession_override(data: dict[str, pd.DataFrame], action: MitigationAction) -> list[dict[str, Any]]:
    supersession = data.get("supersession")
    if supersession is None or supersession.empty:
        return []
    _ensure_column(supersession, "ENABLEOPT", 1)
    mask = _match(supersession, {"ITEM": action.target.get("ITEM"), "LOC": action.target.get("LOC"), "ALTITEM": action.target.get("ALTITEM"), "DMDGROUP": action.target.get("DMDGROUP")})
    if not mask.any():
        return []
    supersession.loc[mask, "ENABLEOPT"] = 1
    if action.parameters.get("conversion_ratio") is not None:
        _ensure_column(supersession, "DRAWQTY", 1.0)
        supersession.loc[mask, "DRAWQTY"] = _number(action.parameters.get("conversion_ratio"), 1.0)
    return [{"entity": "supersession", "rows": int(mask.sum()), "column": "ENABLEOPT", "incremental_cost": _number(action.parameters.get("substitution_penalty"))}]


def _dataframes_to_duckdb(data: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    for entity, df in data.items():
        normalized = df.copy()
        normalized.columns = [_normalize_column(column) for column in normalized.columns]
        conn.register(f"{entity}_df", normalized)
        conn.execute(f'CREATE TABLE "{entity}" AS SELECT * FROM "{entity}_df"')
        conn.unregister(f"{entity}_df")
    return conn


def _copy_dataframes(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {entity.lower(): df.copy() for entity, df in data.items()}


def _coerce_action(action: MitigationAction | dict[str, Any]) -> MitigationAction:
    if isinstance(action, MitigationAction):
        return action
    return MitigationAction(
        action_type=action["action_type"],
        target=action.get("target", {}),
        parameters=action.get("parameters", {}),
        description=action.get("description", ""),
    )


def _match(df: pd.DataFrame, values: dict[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for column, value in values.items():
        if value is None:
            continue
        if column not in df.columns:
            return pd.Series(False, index=df.index)
        mask &= df[column].map(_key) == _key(value)
    return mask


def _ensure_column(df: pd.DataFrame, column: str, default: Any) -> None:
    if column not in df.columns:
        df[column] = default


def _key(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_column(column: Any) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()