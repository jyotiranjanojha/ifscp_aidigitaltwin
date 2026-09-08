'use client';

import { useMemo, useState } from 'react';
import {
  countCriticalResources,
  numberValue,
  type CompareSolverResult,
  type PeggingRecord,
  type SolverResult,
} from '@/src/services/simulationApi';

interface DualSolverComparatorProps {
  result: CompareSolverResult;
}

interface OrderDiffRow {
  orderId: string;
  customer: string;
  item: string;
  reqDate: string;
  heuristicStatus: string;
  lpoptStatus: string;
  laneUsed: string;
  costDelta: number;
  heuristic?: PeggingRecord;
  lpopt?: PeggingRecord;
}

export default function DualSolverComparator({ result }: DualSolverComparatorProps) {
  const [mismatchesOnly, setMismatchesOnly] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);

  const rows = useMemo(
    () => buildOrderDiffRows(result.heuristic_result, result.lpopt_result),
    [result.heuristic_result, result.lpopt_result]
  );
  const visibleRows = mismatchesOnly ? rows.filter((row) => row.heuristicStatus !== row.lpoptStatus) : rows;
  const selectedRow = visibleRows.find((row) => row.orderId === selectedOrderId) || visibleRows[0];
  const heuristicSummary = result.heuristic_result.summary || {};
  const lpSummary = result.lpopt_result.summary || {};

  return (
    <div className="space-y-6">
      <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
            <tr>
              <th className="px-4 py-3 text-left font-semibold">Metric</th>
              <th className="px-4 py-3 text-left font-semibold">Heuristic</th>
              <th className="px-4 py-3 text-left font-semibold">LpOpt</th>
              <th className="px-4 py-3 text-left font-semibold">Solver Gap / Diff</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-700 dark:bg-gray-800">
            <MetricRow label="Total Demand (Units)" heuristic={formatNumber(heuristicSummary.total_demand_qty)} lpopt={formatNumber(lpSummary.total_demand_qty)} diff={formatNumber(numberValue(lpSummary.total_demand_qty) - numberValue(heuristicSummary.total_demand_qty))} />
            <MetricRow label="On-Time Fulfillment % (Met)" heuristic={formatPct(heuristicSummary.met_pct)} lpopt={formatPct(lpSummary.met_pct)} diff={signed(formatPct(result.delta_gap.met_pct_delta))} />
            <MetricRow label="Late-Met % & Average Delay Days" heuristic={`${formatPct(heuristicSummary.late_pct)} / ${numberValue(heuristicSummary.avg_delay_days).toFixed(2)}d`} lpopt={`${formatPct(lpSummary.late_pct)} / ${numberValue(lpSummary.avg_delay_days).toFixed(2)}d`} diff={`${signed(formatPct(result.delta_gap.late_pct_delta))} / ${signed(`${result.delta_gap.avg_delay_delta_days.toFixed(2)}d`)}`} />
            <MetricRow label="Unmet Demand % & Revenue at Risk ($)" heuristic={`${formatPct(heuristicSummary.unmet_pct)} / ${formatCurrency(estimateRevenueAtRisk(result.heuristic_result))}`} lpopt={`${formatPct(lpSummary.unmet_pct)} / ${formatCurrency(estimateRevenueAtRisk(result.lpopt_result))}`} diff={signed(formatPct(result.delta_gap.unmet_pct_delta))} />
            <MetricRow label="Total Landed Cost ($)" heuristic={formatCurrency(heuristicSummary.total_cost)} lpopt={formatCurrency(lpSummary.total_cost)} diff={<span className={result.delta_gap.total_cost_delta >= 0 ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'}>{formatCurrency(Math.abs(result.delta_gap.total_cost_delta))} {result.delta_gap.total_cost_delta >= 0 ? 'saved by LpOpt' : 'higher in LpOpt'}</span>} />
            <MetricRow label="Critical Saturated Resources count" heuristic={String(countCriticalResources(result.heuristic_result))} lpopt={String(countCriticalResources(result.lpopt_result))} diff={signed(String(result.delta_gap.critical_resource_delta))} />
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
        <p className="text-sm font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-300">Solver Trade-Off</p>
        <p className="mt-2 text-gray-800 dark:text-gray-100">{buildTradeoffSummary(result)}</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <NetworkDiffPanel title="Heuristic Network" rows={result.heuristic_result.lane_flows || result.heuristic_result.shipments || []} />
        <NetworkDiffPanel title="LpOpt Network" rows={result.lpopt_result.lane_flows || result.lpopt_result.shipments || []} />
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Order-Level Pegging & Allocation Diff</h3>
          <label className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <input
              type="checkbox"
              checked={mismatchesOnly}
              onChange={(event) => setMismatchesOnly(event.target.checked)}
              className="h-4 w-4 rounded border-gray-300"
            />
            Status Mismatches Only
          </label>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
              <tr>
                {['Order ID', 'Customer', 'Item', 'Req Date', 'Heuristic Status', 'LpOpt Status', 'Sourcing Lane Used', 'Cost Delta'].map((column) => (
                  <th key={column} className="px-3 py-2 text-left font-semibold">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {visibleRows.map((row) => (
                <tr
                  key={row.orderId}
                  onClick={() => setSelectedOrderId(row.orderId)}
                  className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 ${selectedRow?.orderId === row.orderId ? 'bg-amber-50 dark:bg-amber-950/20' : ''}`}
                >
                  <td className="px-3 py-2 font-mono text-gray-900 dark:text-gray-100">{row.orderId}</td>
                  <td className="px-3 py-2 text-gray-700 dark:text-gray-300">{row.customer}</td>
                  <td className="px-3 py-2 text-gray-700 dark:text-gray-300">{row.item}</td>
                  <td className="px-3 py-2 text-gray-700 dark:text-gray-300">{row.reqDate}</td>
                  <td className="px-3 py-2"><StatusBadge status={row.heuristicStatus} /></td>
                  <td className="px-3 py-2"><StatusBadge status={row.lpoptStatus} /></td>
                  <td className="px-3 py-2 text-gray-700 dark:text-gray-300">{row.laneUsed}</td>
                  <td className="px-3 py-2 text-gray-700 dark:text-gray-300">{formatCurrency(row.costDelta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selectedRow && (
          <div className="mt-4 grid gap-3 rounded-lg bg-gray-50 p-4 dark:bg-gray-900/50 md:grid-cols-2">
            <PeggingPath title="Heuristic Pegging Path" record={selectedRow.heuristic} />
            <PeggingPath title="LpOpt Pegging Path" record={selectedRow.lpopt} />
          </div>
        )}
      </div>
    </div>
  );
}

function MetricRow({ label, heuristic, lpopt, diff }: { label: string; heuristic: React.ReactNode; lpopt: React.ReactNode; diff: React.ReactNode }) {
  return (
    <tr>
      <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{label}</td>
      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{heuristic}</td>
      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">{lpopt}</td>
      <td className="px-4 py-3 font-medium text-gray-800 dark:text-gray-200">{diff}</td>
    </tr>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === 'MET' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : status === 'LATE_MET' ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
  return <span className={`rounded-full px-2 py-1 text-xs font-semibold ${color}`}>{status || 'N/A'}</span>;
}

function NetworkDiffPanel({ title, rows }: { title: string; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">{title}</h3>
      <div className="space-y-2">
        {rows.slice(0, 8).map((row, index) => {
          const source = String(row.SOURCE ?? row.source ?? 'Source');
          const dest = String(row.DEST ?? row.dest ?? 'Dest');
          const qty = numberValue(row.quantity ?? row.QUANTITY);
          return (
            <div key={`${source}-${dest}-${index}`} className="rounded-md bg-gray-50 p-3 dark:bg-gray-900/50">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-mono text-gray-800 dark:text-gray-200">{source} → {dest}</span>
                <span className="font-semibold text-blue-700 dark:text-blue-300">{formatNumber(qty)} units</span>
              </div>
              <div className="mt-2 h-2 rounded-full bg-gray-200 dark:bg-gray-700">
                <div className="h-2 rounded-full bg-blue-500" style={{ width: `${Math.min(100, Math.max(8, qty))}%` }} />
              </div>
            </div>
          );
        })}
        {rows.length === 0 && <p className="text-sm text-gray-500 dark:text-gray-400">No lane flow detail returned for this solver.</p>}
      </div>
    </div>
  );
}

function PeggingPath({ title, record }: { title: string; record?: PeggingRecord }) {
  return (
    <div>
      <p className="font-semibold text-gray-900 dark:text-white">{title}</p>
      {record ? (
        <dl className="mt-2 space-y-1 text-sm text-gray-600 dark:text-gray-300">
          <div>Source: {String(record.source_used || 'N/A')}</div>
          <div>Ship Date: {String(record.ship_date || 'N/A')}</div>
          <div>Resources: {(record.res_used || []).join(', ') || 'N/A'}</div>
          <div>Bottleneck: {record.bottleneck_reason || 'None'}</div>
        </dl>
      ) : (
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">No order-level pegging returned by this solver.</p>
      )}
    </div>
  );
}

function buildOrderDiffRows(heuristic: SolverResult, lpopt: SolverResult): OrderDiffRow[] {
  const heuristicRecords = heuristic.pegging_records || [];
  const lpoptRecords = lpopt.pegging_records || [];
  const ids = new Set([...heuristicRecords.map(orderId), ...lpoptRecords.map(orderId)]);

  if (ids.size === 0) {
    return buildShipmentFallbackRows(heuristic, lpopt);
  }

  return Array.from(ids).map((id) => {
    const heuristicRecord = heuristicRecords.find((record) => orderId(record) === id);
    const lpoptRecord = lpoptRecords.find((record) => orderId(record) === id);
    return {
      orderId: id,
      customer: String(heuristicRecord?.customer || lpoptRecord?.customer || 'N/A'),
      item: String(heuristicRecord?.item || lpoptRecord?.item || 'N/A'),
      reqDate: String(heuristicRecord?.req_date || lpoptRecord?.req_date || 'N/A'),
      heuristicStatus: String(heuristicRecord?.status || 'N/A'),
      lpoptStatus: String(lpoptRecord?.status || 'N/A'),
      laneUsed: String(heuristicRecord?.source_used || lpoptRecord?.source_used || 'N/A'),
      costDelta: 0,
      heuristic: heuristicRecord,
      lpopt: lpoptRecord,
    };
  });
}

function buildShipmentFallbackRows(heuristic: SolverResult, lpopt: SolverResult): OrderDiffRow[] {
  const maxRows = Math.max(heuristic.shipments?.length || 0, lpopt.shipments?.length || 0);
  return Array.from({ length: maxRows }).map((_, index) => {
    const heuristicShipment = heuristic.shipments?.[index];
    const lpoptShipment = lpopt.shipments?.[index];
    return {
      orderId: `SHIP-${index + 1}`,
      customer: 'Aggregate',
      item: String(heuristicShipment?.ITEM || lpoptShipment?.ITEM || 'N/A'),
      reqDate: 'N/A',
      heuristicStatus: heuristicShipment ? 'MET' : 'N/A',
      lpoptStatus: lpoptShipment ? 'MET' : 'N/A',
      laneUsed: `${String(heuristicShipment?.SOURCE || lpoptShipment?.SOURCE || 'N/A')} → ${String(heuristicShipment?.DEST || lpoptShipment?.DEST || 'N/A')}`,
      costDelta: numberValue(heuristicShipment?.COST) - numberValue(lpoptShipment?.COST),
    };
  });
}

function buildTradeoffSummary(result: CompareSolverResult): string {
  const saved = result.delta_gap.total_cost_delta;
  const delayDelta = result.delta_gap.avg_delay_delta_days;
  const metDelta = result.delta_gap.met_pct_delta;
  const costPhrase = saved >= 0 ? `LpOpt saved ${formatCurrency(saved)} in total landed cost` : `Heuristic saved ${formatCurrency(Math.abs(saved))} in total landed cost`;
  const delayPhrase = delayDelta > 0 ? `increased average delivery delay by ${delayDelta.toFixed(2)} days` : `reduced average delivery delay by ${Math.abs(delayDelta).toFixed(2)} days`;
  const servicePhrase = metDelta >= 0 ? `improved on-time fulfillment by ${metDelta.toFixed(2)} points` : `reduced on-time fulfillment by ${Math.abs(metDelta).toFixed(2)} points`;
  return `${costPhrase}; compared with heuristic priority pegging, LpOpt ${delayPhrase} and ${servicePhrase}.`;
}

function estimateRevenueAtRisk(result: SolverResult): number {
  const summary = result.summary || {};
  const costPerUnit = numberValue(summary.total_cost) / Math.max(numberValue(summary.met_qty) + numberValue(summary.late_qty), 1);
  return numberValue(summary.unmet_qty) * costPerUnit;
}

function orderId(record: PeggingRecord): string {
  return String(record.order_id || record.ORDER_ID || 'N/A');
}

function formatNumber(value: unknown): string {
  return numberValue(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatPct(value: unknown): string {
  return `${numberValue(value).toFixed(2)}%`;
}

function formatCurrency(value: unknown): string {
  return numberValue(value).toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

function signed(value: string): string {
  return value.startsWith('-') ? value : `+${value}`;
}