from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import pandas as pd
import io
import json
import re
import os

from logger_config import get_logger

from models import SourcingInput, SKUInput, SnopSKUInput, ENTITY_SCHEMA_MAP
from optimizer import run_optimization
from file_parser import (
    parse_filename,
    get_schema_for_entity,
    read_and_normalize_csv,
    validate_dataframe,
    process_upload_file,
    process_multiple_files,
)
from app.api.endpoints.graph import router as graph_router
from app.core.bulk_loader import get_data_summary
from app.services.by_change_exporter import build_by_patch_archive
from app.services.substitutions import parse_supersession_rules, rules_to_dataframe

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app_instance):
    logger.info("FastAPI application startup complete")
    yield
    logger.info("FastAPI application shutting down")


app = FastAPI(
    title="AI Digital Twin - Supply Planning Simulator",
    version="1.0.0",
    description="FastAPI backend for Blue Yonder SCPO file simulation and optimization",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph_router)


@app.get("/")
async def health_check():
    return {"status": "ok"}


def _build_baseline_shipments(sourcing_df: pd.DataFrame, sku_df: pd.DataFrame) -> list[dict]:
    sourcing_records = sourcing_df.to_dict(orient="records")
    sku_records = sku_df.to_dict(orient="records")

    demand = {(r["ITEM"], r["LOC"]): r["DEMAND"] for r in sku_records}
    lanes = [(r["ITEM"], r["SOURCE"], r["DEST"]) for r in sourcing_records]
    base_cost = {(r["ITEM"], r["SOURCE"], r["DEST"]): r["BASE_COST"] for r in sourcing_records}
    max_capacity = {(r["ITEM"], r["SOURCE"], r["DEST"]): r["MAX_CAPACITY"] for r in sourcing_records}

    baseline = []
    remaining_demand = demand.copy()

    for item, source, dest in lanes:
        key = (item, dest)
        if key not in remaining_demand or remaining_demand[key] <= 0:
            continue
        cap = max_capacity.get((item, source, dest), 0)
        qty = min(remaining_demand[key], cap)
        if qty > 0:
            baseline.append({
                "ITEM": item,
                "SOURCE": source,
                "DEST": dest,
                "QUANTITY": round(qty, 2),
                "COST": round(qty * base_cost[(item, source, dest)], 2),
            })
            remaining_demand[key] -= qty

    return baseline


def _canonicalize_sourcing_for_optimizer(sourcing_df: pd.DataFrame) -> pd.DataFrame:
    canonical = sourcing_df.copy()
    if "BASE_COST" not in canonical.columns:
        canonical["BASE_COST"] = pd.to_numeric(canonical.get("PRIORITY", 1.0), errors="coerce").fillna(1.0)
    if "MAX_CAPACITY" not in canonical.columns:
        canonical["MAX_CAPACITY"] = 1_000_000.0
    if "TRANSPORT_TIME" not in canonical.columns and "TRANSLEADTIME" in canonical.columns:
        canonical["TRANSPORT_TIME"] = pd.to_numeric(canonical["TRANSLEADTIME"], errors="coerce").fillna(0.0)
    return canonical


def _canonicalize_demand_for_optimizer(sku_df: pd.DataFrame, forecast_df: pd.DataFrame | None) -> pd.DataFrame:
    if "DEMAND" in sku_df.columns:
        return sku_df

    if forecast_df is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Native BY sku file does not contain DEMAND",
                "required_file": "if_snop_dfutoskufcst-<timestamp>.csv",
                "message": "Upload Demand Forecast so the solver can derive ITEM/LOC/DEMAND from ITEM/SKULOC/TOTFCST.",
            },
        )

    required = {"ITEM", "SKULOC", "TOTFCST"}
    missing = required - set(forecast_df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"error": "Demand forecast file missing required columns", "missing_columns": sorted(missing)},
        )

    demand_df = forecast_df.copy()
    demand_df["TOTFCST"] = pd.to_numeric(demand_df["TOTFCST"], errors="coerce").fillna(0.0)
    demand_df = (
        demand_df.groupby(["ITEM", "SKULOC"], as_index=False)["TOTFCST"]
        .sum()
        .rename(columns={"SKULOC": "LOC", "TOTFCST": "DEMAND"})
    )
    demand_df["PRIORITY"] = 1
    return demand_df


def _canonicalize_inventory_for_optimizer(inventory_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if inventory_df is None:
        return None
    canonical = inventory_df.copy()
    if "QTY" in canonical.columns:
        qty = pd.to_numeric(canonical["QTY"], errors="coerce").fillna(0.0)
        if "ON_HAND" not in canonical.columns:
            canonical["ON_HAND"] = qty
        else:
            canonical["ON_HAND"] = pd.to_numeric(canonical["ON_HAND"], errors="coerce").fillna(qty)
    if "ON_ORDER" not in canonical.columns:
        canonical["ON_ORDER"] = 0.0
    else:
        canonical["ON_ORDER"] = pd.to_numeric(canonical["ON_ORDER"], errors="coerce").fillna(0.0)
    if "ALLOCATED" not in canonical.columns:
        canonical["ALLOCATED"] = 0.0
    else:
        canonical["ALLOCATED"] = pd.to_numeric(canonical["ALLOCATED"], errors="coerce").fillna(0.0)
    if "SAFETY_STOCK" in canonical.columns:
        canonical["SAFETY_STOCK"] = pd.to_numeric(canonical["SAFETY_STOCK"], errors="coerce").fillna(0.0)
    return canonical


def _canonicalize_schedrcpts_for_optimizer(schedrcpts_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if schedrcpts_df is None:
        return None
    canonical = schedrcpts_df.copy()
    if "QTY" in canonical.columns:
        qty = pd.to_numeric(canonical["QTY"], errors="coerce").fillna(0.0)
        if "QUANTITY" not in canonical.columns:
            canonical["QUANTITY"] = qty
        else:
            canonical["QUANTITY"] = pd.to_numeric(canonical["QUANTITY"], errors="coerce").fillna(qty)
    if "SCHED_DATE" in canonical.columns:
        if "DUE_DATE" not in canonical.columns:
            canonical["DUE_DATE"] = canonical["SCHED_DATE"]
        else:
            canonical["DUE_DATE"] = canonical["DUE_DATE"].fillna(canonical["SCHED_DATE"])
    return canonical


def _canonicalize_res_for_optimizer(res_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if res_df is None:
        return None
    canonical = res_df.copy()
    if "RES" in canonical.columns:
        canonical["RESOURCE"] = _fill_series(canonical, "RESOURCE", canonical["RES"])
    canonical["CAPACITY"] = pd.to_numeric(canonical.get("CAPACITY"), errors="coerce").fillna(24.0)
    canonical["EFFICIENCY"] = pd.to_numeric(canonical.get("EFFICIENCY"), errors="coerce").fillna(1.0)
    return canonical


def _canonicalize_bom_for_optimizer(bom_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if bom_df is None:
        return None
    canonical = bom_df.copy()
    if "ITEM" in canonical.columns:
        canonical["PARENT_ITEM"] = _fill_series(canonical, "PARENT_ITEM", canonical["ITEM"])
    if "SUBORD" in canonical.columns:
        canonical["COMPONENT_ITEM"] = _fill_series(canonical, "COMPONENT_ITEM", canonical["SUBORD"])
    if "DRAWQTY" in canonical.columns:
        draw_qty = pd.to_numeric(canonical["DRAWQTY"], errors="coerce").fillna(0.0)
        canonical["QUANTITY_PER"] = _fill_series(canonical, "QUANTITY_PER", draw_qty)
    if "SCRAP_FACTOR" not in canonical.columns:
        canonical["SCRAP_FACTOR"] = 0.0
    else:
        canonical["SCRAP_FACTOR"] = pd.to_numeric(canonical["SCRAP_FACTOR"], errors="coerce").fillna(0.0)
    return canonical


def _canonicalize_productionmethod_for_optimizer(productionmethod_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if productionmethod_df is None:
        return None
    canonical = productionmethod_df.copy()
    if "PRODUCTIONMETHOD" in canonical.columns:
        canonical["METHOD"] = _fill_series(canonical, "METHOD", canonical["PRODUCTIONMETHOD"])
    canonical["YIELD_FACTOR"] = pd.to_numeric(canonical.get("YIELD_FACTOR"), errors="coerce").fillna(1.0)
    canonical["SETUP_TIME"] = pd.to_numeric(canonical.get("SETUP_TIME"), errors="coerce").fillna(0.0)
    canonical["RUN_TIME"] = pd.to_numeric(canonical.get("RUN_TIME", canonical.get("LEADTIME")), errors="coerce").fillna(0.0)
    canonical["BATCH_SIZE"] = pd.to_numeric(canonical.get("BATCH_SIZE", canonical.get("INCQTY")), errors="coerce").fillna(0.0)
    return canonical


def _canonicalize_productionstep_for_optimizer(productionstep_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if productionstep_df is None:
        return None
    canonical = productionstep_df.copy()
    if "PRODUCTIONMETHOD" in canonical.columns:
        canonical["METHOD"] = _fill_series(canonical, "METHOD", canonical["PRODUCTIONMETHOD"])
    if "STEPNUM" in canonical.columns:
        canonical["STEP"] = _fill_series(canonical, "STEP", pd.to_numeric(canonical["STEPNUM"], errors="coerce"))
    if "RES" in canonical.columns:
        canonical["RESOURCE"] = _fill_series(canonical, "RESOURCE", canonical["RES"])
    canonical["SETUP_TIME"] = pd.to_numeric(canonical.get("SETUP_TIME"), errors="coerce").fillna(0.0)
    canonical["RUN_TIME"] = pd.to_numeric(canonical.get("RUN_TIME", canonical.get("PRODDUR")), errors="coerce").fillna(0.0)
    canonical["QUEUE_TIME"] = pd.to_numeric(canonical.get("QUEUE_TIME"), errors="coerce").fillna(0.0)
    canonical["MOVE_TIME"] = pd.to_numeric(canonical.get("MOVE_TIME"), errors="coerce").fillna(0.0)
    canonical["YIELD_FACTOR"] = pd.to_numeric(canonical.get("YIELD_FACTOR"), errors="coerce").fillna(1.0)
    return canonical


def _fill_series(df: pd.DataFrame, column: str, fallback: pd.Series) -> pd.Series:
    if column not in df.columns:
        return fallback
    return df[column].where(df[column].notna(), fallback)


LEGACY_FILENAME_MAP = {
    "sourcing.csv": SourcingInput,
    "sku.csv": SKUInput,
}


async def _detect_and_process_files(files: list[UploadFile]) -> dict:
    """Detect file format and process accordingly."""
    snop_files = []
    legacy_files = {}
    
    for file in files:
        filename = file.filename or ""
        entity = parse_filename(filename)
        if entity:
            snop_files.append(file)
        elif filename.lower() in LEGACY_FILENAME_MAP:
            legacy_files[filename.lower()] = file
        else:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"Unknown file format: {filename}",
                    "supported_formats": [
                        "if_snop_<entity>-YYYYMMDDHHMMSS.csv (e.g., if_snop_locations-20240115120000.csv)",
                        "sourcing.csv, sku.csv (legacy)",
                    ],
                },
            )
    
    results = {}
    
    if snop_files:
        snop_results = await process_multiple_files(snop_files)
        results["snop"] = {entity: data["meta"] for entity, data in snop_results.items()}
    
    if legacy_files:
        legacy_results = {}
        for filename, file in legacy_files.items():
            schema_class = LEGACY_FILENAME_MAP[filename]
            df = await read_and_normalize_csv(file)
            validated = validate_dataframe(df, schema_class, filename)
            legacy_results[filename.replace(".csv", "")] = {
                "data": validated,
                "meta": {"rows": len(validated), "columns": list(df.columns)}
            }
        results["legacy"] = legacy_results
    
    return results


@app.post("/upload/")
async def upload_files(files: list[UploadFile] = File(...)):
    """Single endpoint for all file uploads.
    
    Supports two formats:
    1. S&OP format: if_snop_<entity>-YYYYMMDDHHMMSS.csv
    2. Legacy format: sourcing.csv, sku.csv
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    results = await _detect_and_process_files(files)
    
    return {
        "message": "Files uploaded and validated successfully",
        "results": results,
    }


@app.get("/entities")
async def list_entities():
    return {
        "supported_entities": sorted(ENTITY_SCHEMA_MAP.keys()),
        "filename_pattern": "if_snop_<entity>-YYYYMMDDHHMMSS.csv",
        "legacy_filenames": ["sourcing.csv", "sku.csv"],
        "examples": [
            "if_snop_locations-20240115120000.csv",
            "if_snop_items-20240115120000.csv",
            "if_snop_network-20240115120000.csv",
        ],
    }


@app.get("/api/v1/workspace/data-summary")
async def workspace_data_summary(data_dir: str | None = Query(None, description="Optional BY input folder override")):
    try:
        if data_dir:
            base_workspace = os.path.abspath("./workspace")
            target_path = os.path.abspath(data_dir)
            
            if not target_path.startswith(base_workspace):
                raise HTTPException(status_code=403, detail="Directory access restricted to authorized workspace folder.")
            
        return get_data_summary(data_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to summarize BY workspace data: {exc}")


@app.post("/api/v1/simulation/export-by-patch")
async def export_by_patch(
    files: list[UploadFile] = File(...),
    scenario_deltas: str = Form("[]"),
    scenario_id: str = Form("what_if_scenario"),
    justification: str = Form("Planner-approved what-if mitigation scenario"),
    financial_impact: str = Form("{}"),
):
    if not files:
        raise HTTPException(status_code=400, detail="No BY baseline files provided")
    try:
        deltas = json.loads(scenario_deltas)
        impact = json.loads(financial_impact)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")
    if not isinstance(deltas, list):
        raise HTTPException(status_code=400, detail="scenario_deltas must be a JSON list")
    if not isinstance(impact, dict):
        raise HTTPException(status_code=400, detail="financial_impact must be a JSON object")

    baseline_datasets = {}
    for file in files:
        entity = parse_filename(file.filename or "")
        if not entity:
            raise HTTPException(status_code=400, detail=f"Invalid BY filename: {file.filename}")
        baseline_datasets[entity] = await read_and_normalize_csv(file)

    archive = build_by_patch_archive(
        baseline_datasets,
        deltas,
        scenario_id=scenario_id,
        default_justification=justification,
        financial_impact=impact,
    )
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{scenario_id}_by_patch.zip"'},
    )


@app.post("/run-simulation/")
async def run_simulation(
    sourcing: UploadFile = File(...),
    sku: UploadFile = File(...),
    risk_adjustments: str = Form("{}"),
    solver: str = Query("auto", description="Solver: auto, heuristic, lp"),
    objective_mode: str = Query("MIN_COST", description="Objective: MIN_COST, MAX_DEMAND_FULFILLMENT"),
    bom: UploadFile = File(None),
    res: UploadFile = File(None),
    productionmethod: UploadFile = File(None),
    productionstep: UploadFile = File(None),
    inventory: UploadFile = File(None),
    schedrcpts: UploadFile = File(None),
    dfutoskufcst: UploadFile = File(None),
    items: UploadFile = File(None),
    supersession: UploadFile = File(None),
):
    sourcing_df = await read_and_normalize_csv(sourcing)
    sku_df = await read_and_normalize_csv(sku)
    sku_master_df = sku_df.copy()

    validate_dataframe(sourcing_df, SourcingInput, "sourcing.csv")
    validate_dataframe(sku_df, SKUInput if "DEMAND" in sku_df.columns else SnopSKUInput, "sku.csv")

    optional_files = {
        "bom": (bom, "billofmaterials"),
        "res": (res, "res"),
        "productionmethod": (productionmethod, "productionmethod"),
        "productionstep": (productionstep, "productionstep"),
        "inventory": (inventory, "inventory"),
        "schedrcpts": (schedrcpts, "schedrcpts"),
        "dfutoskufcst": (dfutoskufcst, "dfutoskufcst"),
        "items": (items, "items"),
        "supersession": (supersession, "supersession"),
    }

    optional_dfs = {}
    for key, (file, entity_name) in optional_files.items():
        if file is not None:
            df = await read_and_normalize_csv(file)
            schema_class = ENTITY_SCHEMA_MAP.get(entity_name)
            if schema_class:
                validated_records = validate_dataframe(df, schema_class, f"{entity_name}.csv")
                optional_dfs[key] = pd.DataFrame(validated_records)
            else:
                optional_dfs[key] = df

    try:
        risk_dict = json.loads(risk_adjustments)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in risk_adjustments")

    sourcing_df = _canonicalize_sourcing_for_optimizer(sourcing_df)
    sku_df = _canonicalize_demand_for_optimizer(sku_df, optional_dfs.get("dfutoskufcst"))
    optional_dfs["inventory"] = _canonicalize_inventory_for_optimizer(optional_dfs.get("inventory"))
    optional_dfs["schedrcpts"] = _canonicalize_schedrcpts_for_optimizer(optional_dfs.get("schedrcpts"))
    optional_dfs["res"] = _canonicalize_res_for_optimizer(optional_dfs.get("res"))
    optional_dfs["bom"] = _canonicalize_bom_for_optimizer(optional_dfs.get("bom"))
    optional_dfs["productionmethod"] = _canonicalize_productionmethod_for_optimizer(optional_dfs.get("productionmethod"))
    optional_dfs["productionstep"] = _canonicalize_productionstep_for_optimizer(optional_dfs.get("productionstep"))
    substitution_rules = parse_supersession_rules(
        optional_dfs.get("supersession"),
        items_df=optional_dfs.get("items"),
        sku_df=sku_master_df if "CUST" in sku_master_df.columns else None,
    )
    substitutions_df = rules_to_dataframe(substitution_rules)

    validate_dataframe(sourcing_df, SourcingInput, "sourcing.csv")
    validate_dataframe(sku_df, SKUInput, "sku.csv")

    baseline_shipments = _build_baseline_shipments(sourcing_df, sku_df)
    baseline_total_cost = sum(s["COST"] for s in baseline_shipments)

    opt_result = run_optimization(
        sourcing_df,
        sku_df,
        risk_dict,
        bom_df=optional_dfs.get("bom"),
        res_df=optional_dfs.get("res"),
        productionmethod_df=optional_dfs.get("productionmethod"),
        productionstep_df=optional_dfs.get("productionstep"),
        inventory_df=optional_dfs.get("inventory"),
        schedrcpts_df=optional_dfs.get("schedrcpts"),
        substitutions_df=substitutions_df,
        solver=solver,
        objective_mode=objective_mode,
    )

    if opt_result["status"] == "optimal":
        opt_result["baseline"] = baseline_shipments
        opt_result["baseline_total_cost"] = round(baseline_total_cost, 2)

    return opt_result