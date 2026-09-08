import time
from typing import Optional, Literal
import pandas as pd
from logger_config import get_logger

from heuristic_engine import run_heuristic_optimization
from lpopt_engine import run_lp_optimization

logger = get_logger("solver")

SolverType = Literal["auto", "heuristic", "lp"]


def run_optimization(
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
    solver: SolverType = "auto",
) -> dict:
    """
    Unified optimization entry point with solver selection.

    Args:
        solver: "auto" (try LP first, fallback to heuristic), "heuristic" (greedy only), "lp" (Pyomo+HiGHS only)
    """
    t0 = time.perf_counter()
    logger.info("run_optimization called | solver=%s | sourcing_rows=%d | sku_rows=%d",
                solver, len(sourcing_df), len(sku_df))

    kwargs = dict(
        sourcing_df=sourcing_df, sku_df=sku_df, risk_adjustments=risk_adjustments,
        bom_df=bom_df, res_df=res_df, productionmethod_df=productionmethod_df,
        productionstep_df=productionstep_df, inventory_df=inventory_df,
        schedrcpts_df=schedrcpts_df,
    )

    if solver == "heuristic":
        logger.info("Dispatching to heuristic solver")
        result = run_heuristic_optimization(**kwargs)
    elif solver == "lp":
        logger.info("Dispatching to LP solver")
        result = run_lp_optimization(**kwargs, substitutions_df=substitutions_df)
    else:
        logger.info("Auto mode: attempting LP solver first")
        try:
            result = run_lp_optimization(**kwargs, substitutions_df=substitutions_df)
        except Exception as e:
            logger.error("LP solver raised exception: %s", e, exc_info=True)
            result = {"status": "error", "error": f"LP Solver failed: {str(e)}"}

        if result["status"] in ("error", "infeasible"):
            logger.warning("LP status=%s, falling back to heuristic", result["status"])
            result = run_heuristic_optimization(**kwargs)
            result["fallback"] = True
            result["original_error"] = result.get("error")

    elapsed_ms = (time.perf_counter() - t0) * 1000
    summary = result.get("summary") or {}
    logger.info(
        "run_optimization done | solver=%s | status=%s | cost=%s | met=%.1f%% | elapsed=%.0fms",
        result.get("method"), result.get("status"),
        summary.get("total_cost"), summary.get("met_pct", 0), elapsed_ms,
    )
    return result