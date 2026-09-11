const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

export type SolverType = 'heuristic' | 'lpopt' | 'compare_both';

export type ObjectiveMode = 'MAX_DEMAND_FULFILLMENT' | 'MIN_COST';

export interface ScenarioDelta {
  type: string;
  key: string;
  value: number;
  entity?: string;
  column?: string;
  updates?: Record<string, unknown>;
  justification?: string;
  financial_impact?: Record<string, unknown>;
}

export interface SimulationPayload {
  files: Record<string, File>;
  solver_type: SolverType;
  objective_mode: ObjectiveMode;
  scenario_deltas: ScenarioDelta[];
  risk_adjustments: Record<string, Record<string, number>>;
}

export interface SolverSummary {
  total_demand_qty?: number;
  met_qty?: number;
  met_pct?: number;
  late_qty?: number;
  late_pct?: number;
  avg_delay_days?: number;
  unmet_qty?: number;
  unmet_pct?: number;
  revenue_at_risk?: number;
  total_cost?: number;
  total_landed_cost?: number;
  total_supplied_qty?: number;
  fill_rate_pct?: number;
  objective_mode?: string;
  bottlenecked_resources?: Array<Record<string, unknown>>;
  lane_utilization?: Array<Record<string, unknown>>;
  solve_time_seconds?: number;
}

export interface PeggingRecord {
  order_id?: string;
  item?: string;
  customer?: string;
  req_date?: string;
  ship_date?: string | null;
  status?: 'MET' | 'LATE_MET' | 'UNMET' | string;
  delay_days?: number;
  allocated_qty?: number;
  source_used?: string | null;
  res_used?: string[];
  bottleneck_reason?: string;
  [key: string]: unknown;
}

export interface SolverResult {
  status: 'optimal' | 'infeasible' | 'error' | string;
  method?: string;
  summary?: SolverSummary;
  pegging_records?: PeggingRecord[];
  resource_utilization?: Array<Record<string, unknown>>;
  lane_flows?: Array<Record<string, unknown>>;
  baseline?: Array<Record<string, unknown>>;
  shipments?: Array<Record<string, unknown>>;
  production?: Array<Record<string, unknown>>;
  diagnostics?: BottleneckDiagnostic[];
  substitutions?: Array<Record<string, unknown>>;
  baseline_total_cost?: number;
  total_cost?: number;
  solve_time_ms?: number;
  error?: string;
  [key: string]: unknown;
}

export interface SolverGapAnalysis {
  total_cost_delta: number;
  total_cost_delta_pct: number;
  met_pct_delta: number;
  late_pct_delta: number;
  unmet_pct_delta: number;
  avg_delay_delta_days: number;
  solve_time_delta_seconds: number;
  critical_resource_delta: number;
}

export interface CompareSolverResult {
  heuristic_result: SolverResult;
  lpopt_result: SolverResult;
  delta_gap: SolverGapAnalysis;
}

export type RunSimulationResult = SolverResult | CompareSolverResult;

export async function runSimulation(payload: SimulationPayload): Promise<RunSimulationResult> {
  if (payload.solver_type === 'compare_both') {
    const [heuristicResult, lpoptResult] = await Promise.all([
      runSingleSolver({ ...payload, solver_type: 'heuristic', objective_mode: 'MIN_COST' }),
      runSingleSolver({ ...payload, solver_type: 'lpopt' }),
    ]);

    return {
      heuristic_result: heuristicResult,
      lpopt_result: lpoptResult,
      delta_gap: buildGapAnalysis(heuristicResult, lpoptResult),
    };
  }

  return runSingleSolver(payload);
}

function buildFormData(payload: SimulationPayload): FormData {
  const formData = new FormData();

  Object.entries(payload.files).forEach(([entity, file]) => {
    formData.append(entity, file);
  });

  formData.append('risk_adjustments', JSON.stringify(buildBackendRiskAdjustments(payload.scenario_deltas)));
  formData.append('scenario_deltas', JSON.stringify(payload.scenario_deltas));
  formData.append('solver_type', payload.solver_type);

  return formData;
}

function buildBackendRiskAdjustments(scenarioDeltas: ScenarioDelta[]): Record<string, number> {
  return scenarioDeltas.reduce<Record<string, number>>((riskAdjustments, delta) => {
    if (delta.type === 'sourcing') {
      riskAdjustments[delta.key] = delta.value;
    }
    return riskAdjustments;
  }, {});
}

async function runSingleSolver(payload: SimulationPayload): Promise<SolverResult> {
  const solverParam = payload.solver_type === 'lpopt' ? 'lp' : 'heuristic';
  const objectiveParam = payload.objective_mode || 'MIN_COST';
  const response = await fetch(`${API_BASE}/run-simulation/?solver=${solverParam}&objective_mode=${objectiveParam}`, {
    method: 'POST',
    body: buildFormData(payload),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(JSON.stringify(data.detail || data));
  }

  return normalizeSolverResult(data, payload.solver_type);
}

function normalizeSolverResult(result: SolverResult, solverType: SolverType): SolverResult {
  const totalCost = numberValue(result.total_cost ?? result.summary?.total_cost);
  const solveTimeSeconds = numberValue(result.summary?.solve_time_seconds ?? (numberValue(result.solve_time_ms) / 1000));
  const shipmentQty = sumBy(result.shipments, 'QUANTITY');
  const summary: SolverSummary = {
    total_demand_qty: numberValue(result.summary?.total_demand_qty ?? shipmentQty),
    met_qty: numberValue(result.summary?.met_qty ?? shipmentQty),
    met_pct: numberValue(result.summary?.met_pct ?? (shipmentQty > 0 ? 100 : 0)),
    late_qty: numberValue(result.summary?.late_qty),
    late_pct: numberValue(result.summary?.late_pct),
    avg_delay_days: numberValue(result.summary?.avg_delay_days),
    unmet_qty: numberValue(result.summary?.unmet_qty),
    unmet_pct: numberValue(result.summary?.unmet_pct),
    total_cost: totalCost,
    fill_rate_pct: numberValue(result.summary?.fill_rate_pct),
    total_landed_cost: numberValue(result.summary?.total_landed_cost),
    objective_mode: result.summary?.objective_mode,
    bottlenecked_resources: result.summary?.bottlenecked_resources,
    lane_utilization: result.summary?.lane_utilization,
    solve_time_seconds: solveTimeSeconds,
  };

  return {
    ...result,
    method: result.method || solverType,
    summary,
    total_cost: totalCost,
    solve_time_ms: numberValue(result.solve_time_ms || solveTimeSeconds * 1000),
  };
}

export function buildGapAnalysis(heuristicResult: SolverResult, lpoptResult: SolverResult): SolverGapAnalysis {
  const heuristicSummary = heuristicResult.summary || {};
  const lpSummary = lpoptResult.summary || {};
  const heuristicCost = numberValue(heuristicSummary.total_landed_cost ?? heuristicSummary.total_cost ?? heuristicResult.total_cost);
  const lpCost = numberValue(lpSummary.total_landed_cost ?? lpSummary.total_cost ?? lpoptResult.total_cost);
  const totalCostDelta = heuristicCost - lpCost;

  return {
    total_cost_delta: totalCostDelta,
    total_cost_delta_pct: heuristicCost > 0 ? (totalCostDelta / heuristicCost) * 100 : 0,
    met_pct_delta: numberValue(lpSummary.fill_rate_pct ?? lpSummary.met_pct) - numberValue(heuristicSummary.fill_rate_pct ?? heuristicSummary.met_pct),
    late_pct_delta: numberValue(lpSummary.late_pct) - numberValue(heuristicSummary.late_pct),
    unmet_pct_delta: numberValue(lpSummary.unmet_pct) - numberValue(heuristicSummary.unmet_pct),
    avg_delay_delta_days: numberValue(lpSummary.avg_delay_days) - numberValue(heuristicSummary.avg_delay_days),
    solve_time_delta_seconds: numberValue(lpSummary.solve_time_seconds) - numberValue(heuristicSummary.solve_time_seconds),
    critical_resource_delta: countCriticalResources(lpoptResult) - countCriticalResources(heuristicResult),
  };
}

export function isCompareResult(result: RunSimulationResult | null): result is CompareSolverResult {
  return Boolean(result && 'heuristic_result' in result && 'lpopt_result' in result);
}

export function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

export function sumBy(rows: Array<Record<string, unknown>> | undefined, key: string): number {
  return (rows || []).reduce((total, row) => total + numberValue(row[key]), 0);
}

export function countCriticalResources(result: SolverResult): number {
  return (result.resource_utilization || []).filter((row) => numberValue(row.utilization_pct) >= 95).length;
}

export interface BottleneckDiagnostic {
  order_id: string;
  item: string;
  customer: string;
  unmet_qty: number;
  root_cause: string;
  bottleneck_entity: string;
  suggested_mitigation: string;
}

export async function exportByPatchPack(params: {
  files: Record<string, File>;
  scenario_deltas: ScenarioDelta[];
  scenario_id?: string;
  justification?: string;
  financial_impact?: Record<string, unknown>;
}): Promise<Blob> {
  const formData = new FormData();
  Object.entries(params.files).forEach(([_entity, file]) => {
    formData.append('files', file);
  });
  formData.append('scenario_deltas', JSON.stringify(params.scenario_deltas));
  formData.append('scenario_id', params.scenario_id || 'planner_what_if');
  formData.append('justification', params.justification || 'Planner-approved mitigation scenario');
  formData.append('financial_impact', JSON.stringify(params.financial_impact || {}));

  const response = await fetch(`${API_BASE}/api/v1/simulation/export-by-patch`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(JSON.stringify(data.detail || data || 'Export failed'));
  }
  return response.blob();
}