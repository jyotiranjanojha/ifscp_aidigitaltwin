from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

import duckdb
import pandas as pd


MAX_UTILIZATION_HEALTHY = 0.85
MAX_UTILIZATION_WARNING = 1.0
DEFAULT_LANE_CAPACITY = 1_000_000.0


@dataclass(frozen=True)
class GraphTopologyResult:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "summary": self.summary,
        }


class GraphTopologySerializer:
    """Serializes DuckDB supply-chain tables into node-link graph data for visualization."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self.conn = conn

    def build_network_graph(self, scenario_id: str) -> dict[str, Any]:
        locations_df = self._table("locations")
        res_df = self._table("res")
        customer_df = self._table("customer")
        items_df = self._table("items")
        network_df = self._table("network")
        sourcing_df = self._table("sourcing")
        bom_df = self._table("billofmaterials")
        inventory_df = self._table("inventory")
        sku_df = self._table("sku")
        res_capacity_df = self._table("res")

        nodes = self._build_nodes(locations_df, res_df, customer_df, items_df, inventory_df, sku_df, res_capacity_df)
        node_ids = {n["id"] for n in nodes}

        edges = self._build_edges(network_df, sourcing_df, bom_df, node_ids, items_df)
        self._attach_flow_metrics(edges, sourcing_df)

        self._compute_node_status(nodes, edges)

        summary = self._build_summary(nodes, edges)
        return GraphTopologyResult(nodes=nodes, edges=edges, summary=summary).to_dict()

    def build_bom_graph(self, parent_item: str, loc: Optional[str] = None) -> dict[str, Any]:
        bom_df = self._table("billofmaterials")
        alt_bom_df = self._table("altbillofmaterials")
        items_df = self._table("items")

        bom_nodes: list[dict[str, Any]] = []
        bom_edges: list[dict[str, Any]] = []
        visited: set[str] = set()

        self._traverse_bom(parent_item, loc, bom_df, alt_bom_df, items_df, bom_nodes, bom_edges, visited, depth=0)

        return {
            "nodes": bom_nodes,
            "edges": bom_edges,
            "root_item": parent_item,
            "root_loc": loc,
            "summary": {
                "total_nodes": len(bom_nodes),
                "total_edges": len(bom_edges),
                "max_depth": max((n.get("depth", 0) for n in bom_nodes), default=0),
            },
        }

    def _build_nodes(
        self,
        locations_df: pd.DataFrame,
        res_df: pd.DataFrame,
        customer_df: pd.DataFrame,
        items_df: pd.DataFrame,
        inventory_df: pd.DataFrame,
        sku_df: pd.DataFrame,
        res_capacity_df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for row in locations_df.to_dict(orient="records"):
            loc_id = _text(row.get("LOC"))
            if not loc_id or loc_id in seen_ids:
                continue
            seen_ids.add(loc_id)
            node_type = _infer_location_type(row)
            lat = _float(row.get("LATITUDE"), None)
            lng = _float(row.get("LONGITUDE"), None)
            label = _text(row.get("DESCR")) or _text(row.get("LOC_NAME")) or loc_id
            metrics = _location_metrics(loc_id, inventory_df, sku_df)
            nodes.append({
                "id": f"LOC_{loc_id}",
                "label": label,
                "type": node_type,
                "coordinates": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
                "status": _HEALTHY,
                "metrics": metrics,
                "loc_ref": loc_id,
            })

        for row in res_df.to_dict(orient="records"):
            res_id = _text(row.get("RES") or row.get("RESOURCE"))
            loc_id = _text(row.get("LOC"))
            if not res_id or not loc_id:
                continue
            node_id = f"RES_{res_id}_{loc_id}"
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            capacity = _float(row.get("CAPACITY"), 24.0)
            efficiency = _float(row.get("EFFICIENCY"), 1.0)
            utilized = _float(row.get("UTILIZATION"), 0.0) * capacity
            util_pct = (utilized / capacity * 100.0) if capacity > 0 else 0.0
            lat = _float(row.get("LATITUDE"), None)
            lng = _float(row.get("LONGITUDE"), None)
            if lat is None or lng is None:
                parent_node = next((n for n in nodes if n.get("loc_ref") == loc_id), None)
                if parent_node and parent_node.get("coordinates"):
                    lat = parent_node["coordinates"]["lat"]
                    lng = parent_node["coordinates"]["lng"]
            nodes.append({
                "id": node_id,
                "label": _text(row.get("DESCR") or row.get("RESOURCE_NAME")) or res_id,
                "type": "resource",
                "coordinates": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
                "status": _utilization_status(util_pct),
                "metrics": {
                    "capacity": round(capacity, 4),
                    "utilized": round(utilized, 4),
                    "utilization_pct": round(util_pct, 2),
                    "efficiency": round(efficiency, 4),
                },
                "loc_ref": loc_id,
            })

        for row in customer_df.to_dict(orient="records"):
            cust_id = _text(row.get("CUST"))
            if not cust_id or cust_id in seen_ids:
                continue
            seen_ids.add(cust_id)
            lat = _float(row.get("LATITUDE"), None)
            lng = _float(row.get("LONGITUDE"), None)
            nodes.append({
                "id": f"CUST_{cust_id}",
                "label": _text(row.get("DESCR") or row.get("CUSTOMER_NAME")) or cust_id,
                "type": "customer",
                "coordinates": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
                "status": _HEALTHY,
                "metrics": {
                    "capacity": 0.0,
                    "utilized": 0.0,
                    "utilization_pct": 0.0,
                    "inventory_on_hand": 0.0,
                },
            })

        return nodes

    def _build_edges(
        self,
        network_df: pd.DataFrame,
        sourcing_df: pd.DataFrame,
        bom_df: pd.DataFrame,
        node_ids: set[str],
        items_df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        seen_edge_ids: set[str] = set()

        for row in network_df.to_dict(orient="records"):
            source = _text(row.get("SOURCE"))
            dest = _text(row.get("DEST"))
            if not source or not dest:
                continue
            src_id = f"LOC_{source}" if f"LOC_{source}" in node_ids else source
            tgt_id = f"LOC_{dest}" if f"LOC_{dest}" in node_ids else dest
            edge_id = f"NET_{source}->{dest}"
            if edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge_id)
            transit = int(_float(row.get("TRANSLEADTIME") or row.get("LEAD_TIME"), 0))
            edges.append({
                "id": edge_id,
                "source": src_id,
                "target": tgt_id,
                "baseline_volume": 0.0,
                "simulated_volume": 0.0,
                "delta_volume": 0.0,
                "transit_time_days": transit,
                "cost_per_unit": 0.0,
                "is_congested": False,
                "items": [],
            })

        for row in sourcing_df.to_dict(orient="records"):
            item = _text(row.get("ITEM"))
            source = _text(row.get("SOURCE"))
            dest = _text(row.get("DEST"))
            if not item or not source or not dest:
                continue
            src_id = f"LOC_{source}" if f"LOC_{source}" in node_ids else source
            tgt_id = f"LOC_{dest}" if f"LOC_{dest}" in node_ids else dest
            edge_id = f"SUP_{source}->{dest}_{item}"
            if edge_id in seen_edge_ids:
                existing = next((e for e in edges if e["id"] == edge_id), None)
                if existing and item not in existing["items"]:
                    existing["items"].append(item)
                continue
            seen_edge_ids.add(edge_id)
            cost = _float(row.get("BASE_COST"), 0.0)
            transit = int(_float(row.get("TRANSPORT_TIME"), 0))
            max_cap = _float(row.get("MAX_CAPACITY"), DEFAULT_LANE_CAPACITY)
            edges.append({
                "id": edge_id,
                "source": src_id,
                "target": tgt_id,
                "baseline_volume": 0.0,
                "simulated_volume": 0.0,
                "delta_volume": 0.0,
                "transit_time_days": transit,
                "cost_per_unit": cost,
                "is_congested": False,
                "items": [item],
                "max_capacity": max_cap,
            })

        for row in bom_df.to_dict(orient="records"):
            parent = _text(row.get("PARENT_ITEM") or row.get("ITEM"))
            component = _text(row.get("COMPONENT_ITEM") or row.get("SUBORD"))
            loc = _text(row.get("LOC"))
            if not parent or not component:
                continue
            edge_id = f"BOM_{parent}->{component}"
            if edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge_id)
            draw_qty = _float(row.get("QUANTITY_PER") or row.get("DRAWQTY"), 1.0)
            bom_node_src = f"ITEM_{parent}" if f"ITEM_{parent}" in node_ids else parent
            bom_node_tgt = f"ITEM_{component}" if f"ITEM_{component}" in node_ids else component
            edges.append({
                "id": edge_id,
                "source": bom_node_src,
                "target": bom_node_tgt,
                "baseline_volume": 0.0,
                "simulated_volume": 0.0,
                "delta_volume": 0.0,
                "transit_time_days": 0,
                "cost_per_unit": 0.0,
                "is_congested": False,
                "items": [parent],
                "draw_qty_per_unit": draw_qty,
                "loc": loc,
                "edge_type": "bom",
            })

        return edges

    def _attach_flow_metrics(
        self, edges: list[dict[str, Any]], sourcing_df: pd.DataFrame
    ) -> None:
        if sourcing_df.empty:
            return

        lane_volume: dict[tuple[str, str, str], float] = defaultdict(float)
        for row in sourcing_df.to_dict(orient="records"):
            item = _text(row.get("ITEM"))
            source = _text(row.get("SOURCE"))
            dest = _text(row.get("DEST"))
            if item and source and dest:
                lane_volume[(item, source, dest)] += _float(row.get("MAX_CAPACITY"), 0.0)

        for edge in edges:
            if edge.get("edge_type") == "bom":
                continue
            parts = edge["id"].replace("NET_", "").replace("SUP_", "").split("->")
            if len(parts) < 2:
                continue
            src_raw = parts[0].split("_", 1)[-1] if parts[0].startswith("LOC_") else parts[0]
            tgt_raw = parts[1].split("_", 1)[0] if parts[1].startswith("LOC_") else parts[1].split("_")[0]
            total_volume = 0.0
            total_cost = 0.0
            for (item, source, dest), vol in lane_volume.items():
                if source == src_raw and dest == tgt_raw:
                    total_volume += vol
                    total_cost += vol * (edge.get("cost_per_unit", 0.0))
            edge["baseline_volume"] = round(total_volume, 4)
            edge["simulated_volume"] = round(total_volume, 4)
            edge["delta_volume"] = 0.0
            if total_volume > 0 and edge.get("cost_per_unit", 0.0) == 0.0:
                edge["cost_per_unit"] = round(total_cost / total_volume, 6) if total_volume else 0.0
            max_cap = edge.get("max_capacity", DEFAULT_LANE_CAPACITY)
            if max_cap > 0:
                edge["is_congested"] = total_volume >= max_cap

    def _compute_node_status(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> None:
        unmet_demand_nodes: set[str] = set()
        for edge in edges:
            if edge.get("delta_volume", 0) < 0:
                unmet_demand_nodes.add(edge["target"])

        for node in nodes:
            metrics = node.get("metrics", {})
            util_pct = metrics.get("utilization_pct", 0.0)
            if node["id"] in unmet_demand_nodes:
                node["status"] = "BOTTLENECK"
            elif util_pct > 100.0:
                node["status"] = "BOTTLENECK"
            elif util_pct > 85.0:
                node["status"] = "WARNING"
            else:
                node["status"] = "HEALTHY"

    def _build_summary(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        type_counts: dict[str, int] = defaultdict(int)
        for node in nodes:
            type_counts[node["type"]] += 1

        status_counts: dict[str, int] = defaultdict(int)
        for node in nodes:
            status_counts[node.get("status", "HEALTHY")] += 1

        total_baseline = sum(e.get("baseline_volume", 0) for e in edges)
        total_simulated = sum(e.get("simulated_volume", 0) for e in edges)
        congested_edges = sum(1 for e in edges if e.get("is_congested"))

        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "nodes_by_type": dict(type_counts),
            "nodes_by_status": dict(status_counts),
            "congested_edges": congested_edges,
            "total_baseline_volume": round(total_baseline, 4),
            "total_simulated_volume": round(total_simulated, 4),
            "total_flow_delta": round(total_simulated - total_baseline, 4),
        }

    def _traverse_bom(
        self,
        parent_item: str,
        loc: Optional[str],
        bom_df: pd.DataFrame,
        alt_bom_df: pd.DataFrame,
        items_df: pd.DataFrame,
        bom_nodes: list[dict[str, Any]],
        bom_edges: list[dict[str, Any]],
        visited: set[str],
        depth: int,
    ) -> None:
        if parent_item in visited:
            bom_nodes.append({
                "id": f"BOM_{parent_item}_CYCLE",
                "label": parent_item,
                "type": "bom_item",
                "status": "WARNING",
                "depth": depth,
                "is_cycle": True,
            })
            return
        visited.add(parent_item)

        item_label = self._item_label(parent_item, items_df)
        bom_nodes.append({
            "id": f"BOM_{parent_item}",
            "label": item_label,
            "type": "bom_item",
            "status": "HEALTHY",
            "depth": depth,
            "is_cycle": False,
        })

        if bom_df.empty:
            return

        filtered = bom_df
        if loc:
            loc_col = "LOC" if "LOC" in bom_df.columns else None
            if loc_col:
                filtered = bom_df[bom_df[loc_col].map(lambda v: _text(v) == loc)]

        parent_col = "PARENT_ITEM" if "PARENT_ITEM" in filtered.columns else "ITEM"
        for row in filtered.to_dict(orient="records"):
            row_parent = _text(row.get(parent_col))
            component = _text(row.get("COMPONENT_ITEM") or row.get("SUBORD"))
            if row_parent != parent_item or not component:
                continue
            draw_qty = _float(row.get("QUANTITY_PER") or row.get("DRAWQTY"), 1.0)
            bom_edges.append({
                "id": f"BOM_{parent_item}->{component}",
                "source": f"BOM_{parent_item}",
                "target": f"BOM_{component}",
                "draw_qty_per_unit": draw_qty,
                "edge_type": "bom",
            })
            self._traverse_bom(
                component, loc, bom_df, alt_bom_df, items_df,
                bom_nodes, bom_edges, visited, depth + 1,
            )

        if not alt_bom_df.empty:
            alt_filtered = alt_bom_df
            if loc and "LOC" in alt_bom_df.columns:
                alt_filtered = alt_bom_df[alt_bom_df["LOC"].map(lambda v: _text(v) == loc)]
            for row in alt_filtered.to_dict(orient="records"):
                row_parent = _text(row.get("PARENT_ITEM") or row.get("ITEM"))
                alt_component = _text(row.get("ALTSUBORD") or row.get("SUBORD"))
                if row_parent != parent_item or not alt_component:
                    continue
                draw_qty = _float(row.get("QUANTITY_PER") or row.get("DRAWQTY"), 1.0)
                bom_edges.append({
                    "id": f"ALT_BOM_{parent_item}->{alt_component}",
                    "source": f"BOM_{parent_item}",
                    "target": f"BOM_{alt_component}",
                    "draw_qty_per_unit": draw_qty,
                    "edge_type": "alt_bom",
                })
                self._traverse_bom(
                    alt_component, loc, bom_df, alt_bom_df, items_df,
                    bom_nodes, bom_edges, visited, depth + 1,
                )

    def _item_label(self, item_id: str, items_df: pd.DataFrame) -> str:
        if items_df.empty:
            return item_id
        match = items_df[items_df["ITEM"].map(lambda v: _text(v) == item_id)]
        if not match.empty:
            row = match.iloc[0]
            return _text(row.get("DESCR")) or _text(row.get("ITEM_NAME")) or item_id
        return item_id

    def _table(self, table_name: str) -> pd.DataFrame:
        exists = self.conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE lower(table_name) = ?",
            [table_name.lower()],
        ).fetchone()[0]
        if not exists:
            return pd.DataFrame()
        df = self.conn.execute(f'SELECT * FROM "{table_name}"').fetchdf()
        df.columns = [_normalize_column_name(col) for col in df.columns]
        return df


_HEALTHY = "HEALTHY"


def _infer_location_type(row: dict[str, Any]) -> str:
    loc_type = _text(row.get("LOC_TYPE"))
    if loc_type:
        lt = loc_type.upper()
        if lt in ("SUP", "SUPPLIER", "VENDOR"):
            return "supplier"
        if lt in ("PLT", "PLANT", "MFG", "FACTORY"):
            return "plant"
        if lt in ("DC", "DIST", "DISTRIBUTION", "WH", "WAREHOUSE"):
            return "dc"
    plan_module = _text(row.get("U_PLANMODULE"))
    if plan_module:
        pm = plan_module.upper()
        if "SUPP" in pm:
            return "supplier"
        if "PLANT" in pm or "MFG" in pm or "PROD" in pm:
            return "plant"
        if "DC" in pm or "DIST" in pm or "WH" in pm:
            return "dc"
    loc_name = (_text(row.get("LOC_NAME")) or _text(row.get("DESCR")) or "").upper()
    if "SUPPLIER" in loc_name or "VENDOR" in loc_name:
        return "supplier"
    if "PLANT" in loc_name or "FAB" in loc_name or "FACTORY" in loc_name:
        return "plant"
    if "DC" in loc_name or "DISTRIBUTION" in loc_name or "WAREHOUSE" in loc_name:
        return "dc"
    return "plant"


def _location_metrics(loc_id: str, inventory_df: pd.DataFrame, sku_df: pd.DataFrame) -> dict[str, float]:
    on_hand = 0.0
    if not inventory_df.empty and "LOC" in inventory_df.columns:
        loc_inv = inventory_df[inventory_df["LOC"].map(lambda v: _text(v) == loc_id)]
        for col in ("ON_HAND", "QTY", "AVAILABLE"):
            if col in loc_inv.columns:
                on_hand = pd.to_numeric(loc_inv[col], errors="coerce").fillna(0.0).sum()
                if on_hand > 0:
                    break
    capacity = 0.0
    utilized = 0.0
    if not sku_df.empty and "LOC" in sku_df.columns:
        loc_sku = sku_df[sku_df["LOC"].map(lambda v: _text(v) == loc_id)]
        if "DEMAND" in loc_sku.columns:
            capacity = pd.to_numeric(loc_sku["DEMAND"], errors="coerce").fillna(0.0).sum()
        elif "OHPOST" in loc_sku.columns:
            capacity = pd.to_numeric(loc_sku["OHPOST"], errors="coerce").fillna(0.0).sum()
        utilized = capacity * 0.5
    util_pct = (utilized / capacity * 100.0) if capacity > 0 else 0.0
    return {
        "capacity": round(capacity, 4),
        "utilized": round(utilized, 4),
        "utilization_pct": round(util_pct, 2),
        "inventory_on_hand": round(on_hand, 4),
    }


def _utilization_status(util_pct: float) -> str:
    if util_pct > 100.0:
        return "BOTTLENECK"
    if util_pct > 85.0:
        return "WARNING"
    return "HEALTHY"


def _normalize_column_name(column: object) -> str:
    return str(column).replace("\ufeff", "").replace("\xa0", "").strip().upper()


def _text(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _float(value: Any, default: Optional[float]) -> float:
    if value is None or pd.isna(value):
        return default if default is not None else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return default if default is not None else 0.0


def build_network_graph(conn: duckdb.DuckDBPyConnection, scenario_id: str) -> dict[str, Any]:
    return GraphTopologySerializer(conn).build_network_graph(scenario_id)


def build_bom_graph(conn: duckdb.DuckDBPyConnection, parent_item: str, loc: Optional[str] = None) -> dict[str, Any]:
    return GraphTopologySerializer(conn).build_bom_graph(parent_item, loc)
