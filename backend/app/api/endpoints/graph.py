from __future__ import annotations

import json
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.core.bulk_loader import load_by_csv_pack, resolve_data_dir
from app.services.graph_service import build_bom_graph, build_network_graph

router = APIRouter(prefix="/api/v1/simulation", tags=["graph"])


def _to_serializable(obj):
    """Convert numpy/pandas types to JSON-safe Python natives."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    return obj


@router.get("/network-graph/{scenario_id}")
async def get_network_graph(
    scenario_id: str,
    data_dir: Optional[str] = Query(None, description="Optional BY input folder override"),
) -> dict:
    """Serialize the full supply-chain network into a node-link graph for React Flow / Deck.gl."""
    try:
        load_result = load_by_csv_pack(data_dir)
        result = build_network_graph(load_result.conn, scenario_id)
        result["scenario_id"] = scenario_id
        result["data_dir"] = str(load_result.data_dir)
        return _to_serializable(result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build network graph: {exc}")


@router.get("/bom-graph/{parent_item}")
async def get_bom_graph(
    parent_item: str,
    loc: Optional[str] = Query(None, description="Optional location filter for BOM explosion"),
    data_dir: Optional[str] = Query(None, description="Optional BY input folder override"),
) -> dict:
    """Build a multi-level BOM sub-graph from bill-of-materials data."""
    try:
        load_result = load_by_csv_pack(data_dir)
        result = build_bom_graph(load_result.conn, parent_item, loc=loc)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build BOM graph: {exc}")
