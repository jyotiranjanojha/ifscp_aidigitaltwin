'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  Handle,
  Position,
  BaseEdge,
  getBezierPath,
  Background,
  Controls,
  MiniMap,
} from '@xyflow/react';
import type {
  NodeProps,
  EdgeProps,
  Node,
  Edge,
  OnNodesChange,
  OnEdgesChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Factory,
  GitBranch,
  Package,
  Sliders,
  Truck,
  Users,
  Warehouse,
  X,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const ECHELON_X_GAP = 280;
const ECHELON_Y_GAP = 120;
const NODE_WIDTH = 220;

const TIER_MAP: Record<string, number> = {
  supplier: 0,
  plant: 1,
  resource: 1,
  dc: 2,
  customer: 3,
};

const TYPE_COLORS: Record<string, { bg: string; border: string; text: string; badge: string }> = {
  supplier: { bg: 'bg-violet-50', border: 'border-violet-300', text: 'text-violet-800', badge: 'bg-violet-100 text-violet-700' },
  plant: { bg: 'bg-blue-50', border: 'border-blue-300', text: 'text-blue-800', badge: 'bg-blue-100 text-blue-700' },
  resource: { bg: 'bg-amber-50', border: 'border-amber-300', text: 'text-amber-800', badge: 'bg-amber-100 text-amber-700' },
  dc: { bg: 'bg-emerald-50', border: 'border-emerald-300', text: 'text-emerald-800', badge: 'bg-emerald-100 text-emerald-700' },
  customer: { bg: 'bg-rose-50', border: 'border-rose-300', text: 'text-rose-800', badge: 'bg-rose-100 text-rose-700' },
  bom_item: { bg: 'bg-slate-50', border: 'border-slate-300', text: 'text-slate-800', badge: 'bg-slate-100 text-slate-700' },
};

const TYPE_ICONS: Record<string, React.FC<{ className?: string }>> = {
  supplier: Truck,
  plant: Factory,
  resource: Cpu,
  dc: Warehouse,
  customer: Users,
  bom_item: Package,
};

function Cpu({ className }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="16" height="16" x="4" y="4" rx="2" />
      <rect width="6" height="6" x="9" y="9" rx="1" />
      <path d="M15 2v2" /><path d="M15 20v2" /><path d="M2 15h2" /><path d="M2 9h2" /><path d="M20 15h2" /><path d="M20 9h2" /><path d="M9 2v2" /><path d="M9 20v2" />
    </svg>
  );
}

interface GraphNodeData extends Record<string, unknown> {
  label: string;
  type: string;
  status: string;
  metrics: {
    capacity: number;
    utilized: number;
    utilization_pct: number;
    inventory_on_hand?: number;
    efficiency?: number;
  };
  coordinates?: { lat: number; lng: number } | null;
  depth?: number;
  is_cycle?: boolean;
  draw_qty_per_unit?: number;
  tier: number;
  onClick?: (nodeId: string) => void;
}

type GraphNode = Node<GraphNodeData>;

interface FlowEdgeData extends Record<string, unknown> {
  baseline_volume: number;
  simulated_volume: number;
  delta_volume: number;
  transit_time_days: number;
  cost_per_unit: number;
  is_congested: boolean;
  items?: string[];
  edge_type?: string;
}

type FlowEdge = Edge<FlowEdgeData>;

interface WhatIfOverride {
  nodeId: string;
  nodeLabel: string;
  nodeType: string;
  capacityDelta: number;
  leadTimeDelta: number;
  originalCapacity: number;
  originalUtilPct: number;
}

interface SupplyChainGraphTwinProps {
  scenarioId?: string;
  focusNodeId?: string;
  focusLabel?: string;
  onOverrideApply?: (overrides: WhatIfOverride[]) => void;
}

export default function SupplyChainGraphTwin(props: SupplyChainGraphTwinProps) {
  return (
    <ReactFlowProvider>
      <SupplyChainGraphTwinInner {...props} />
    </ReactFlowProvider>
  );
}

function SupplyChainGraphTwinInner({ scenarioId = 'baseline', focusNodeId, focusLabel, onOverrideApply }: SupplyChainGraphTwinProps) {
  const [rawNodes, setRawNodes] = useState<GraphNode[]>([]);
  const [rawEdges, setRawEdges] = useState<FlowEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Map<string, WhatIfOverride>>(new Map());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);
  const { fitView } = useReactFlow();

  useEffect(() => {
    if (!focusNodeId || !nodes.length) return;
    const matchId = nodes.find((n) => n.id === focusNodeId || (n.data as GraphNodeData)?.label?.toLowerCase() === focusLabel?.toLowerCase())?.id;
    if (matchId) {
      setTimeout(() => fitView({ nodes: [{ id: matchId }], padding: 0.4, duration: 500 }), 100);
    }
  }, [focusNodeId, focusLabel, nodes, fitView]);

  useEffect(() => {
    let cancelled = false;
    async function fetchGraph() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/api/v1/simulation/network-graph/${scenarioId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;

        const positioned = layoutEchelon(data.nodes || []);
        const graphEdges = buildEdges(data.edges || [], data.nodes || []);
        setRawNodes(positioned);
        setRawEdges(graphEdges);
        setSummary(data.summary || null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load graph');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchGraph();
    return () => { cancelled = true; };
  }, [scenarioId]);

  useEffect(() => {
    setNodes(rawNodes);
  }, [rawNodes, setNodes]);

  useEffect(() => {
    setEdges(rawEdges);
  }, [rawEdges, setEdges]);

  const handleNodeClick = useCallback((_: React.MouseEvent, node: GraphNode) => {
    setSelectedNode(node.id);
    setDrawerOpen(true);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setDrawerOpen(false);
    setSelectedNode(null);
  }, []);

  const selectedNodeData = useMemo(() => {
    if (!selectedNode) return null;
    return rawNodes.find((n) => n.id === selectedNode) || null;
  }, [selectedNode, rawNodes]);

  const existingOverride = selectedNode ? overrides.get(selectedNode) : undefined;

  const handleApplyOverride = useCallback((override: WhatIfOverride) => {
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(override.nodeId, override);
      return next;
    });
    setEdges((prev) => prev.map((edge) => {
      if (edge.source === override.nodeId || edge.target === override.nodeId) {
        const data = { ...edge.data } as FlowEdgeData;
        const factor = 1 + override.capacityDelta / 100;
        data.simulated_volume = data.baseline_volume * factor;
        data.delta_volume = data.simulated_volume - data.baseline_volume;
        const colors = getEdgeColors(data);
        return { ...edge, data, style: { ...edge.style, stroke: colors.stroke, strokeWidth: colors.strokeWidth } };
      }
      return edge;
    }));
    setNodes((prev) => prev.map((node) => {
      if (node.id !== override.nodeId) return node;
      const data = { ...node.data } as GraphNodeData;
      const factor = 1 + override.capacityDelta / 100;
      const newCap = Math.max(data.metrics.capacity * factor, 0);
      const newUtil = newCap > 0 ? (data.metrics.utilized / newCap) * 100 : 0;
      data.metrics = { ...data.metrics, capacity: newCap, utilization_pct: newUtil };
      data.status = getNodeStatus(newUtil);
      return { ...node, data };
    }));
    onOverrideApply?.(Array.from(new Map([...overrides, [override.nodeId, override]]).values()));
    setDrawerOpen(false);
    setSelectedNode(null);
  }, [overrides, setEdges, setNodes, onOverrideApply]);

  const nodeTypes = useMemo(() => ({
    facility: FacilityNode,
    resource: ResourceNode,
    customer: CustomerNode,
    bom: BomNode,
  }), []);

  const edgeTypes = useMemo(() => ({
    animatedFlow: AnimatedFlowEdge,
  }), []);

  if (loading) {
    return (
      <div className="flex h-[600px] items-center justify-center rounded-lg border border-slate-200 bg-white">
        <div className="text-center">
          <GitBranch className="mx-auto h-8 w-8 animate-pulse text-blue-500" />
          <p className="mt-3 text-sm font-medium text-slate-600">Loading supply chain topology...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-[600px] items-center justify-center rounded-lg border border-red-200 bg-red-50">
        <div className="text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-red-400" />
          <p className="mt-3 text-sm font-medium text-red-700">{error}</p>
          <p className="mt-1 text-xs text-red-500">Ensure the backend is running and BY files are loaded.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">Multi-Echelon Network Graph</h2>
          <p className="text-sm text-slate-500">Interactive DAG showing Suppliers &rarr; Plants &rarr; DCs &rarr; Customers</p>
        </div>
        {summary && (
          <div className="flex gap-3 text-xs">
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
              {(summary.total_nodes as number) || 0} nodes
            </span>
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
              {(summary.total_edges as number) || 0} edges
            </span>
            {(summary.congested_edges as number) > 0 && (
              <span className="rounded-md bg-red-100 px-2 py-1 font-medium text-red-700">
                {(summary.congested_edges as number)} congested
              </span>
            )}
          </div>
        )}
      </div>

      <div className="h-[600px] overflow-hidden rounded-lg border border-slate-200 bg-white">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange as OnNodesChange}
          onEdgesChange={onEdgesChange as OnEdgesChange}
          onNodeClick={handleNodeClick}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={2}
          defaultEdgeOptions={{ type: 'animatedFlow' }}
        >
          <Background color="#e2e8f0" gap={20} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              const data = node.data as GraphNodeData;
              const colors = TYPE_COLORS[data?.type] || TYPE_COLORS.plant;
              return colors.border.replace('border-', '').replace('-300', '-400');
            }}
            maskColor="rgba(255,255,255,0.7)"
          />
        </ReactFlow>
      </div>

      <LegendBar />

      {drawerOpen && selectedNodeData && (
        <WhatIfDrawer
          node={selectedNodeData}
          existingOverride={existingOverride}
          onApply={handleApplyOverride}
          onClose={handleCloseDrawer}
        />
      )}
    </div>
  );
}

function layoutEchelon(rawNodes: Array<Record<string, unknown>>): GraphNode[] {
  const tierGroups: Map<number, Array<Record<string, unknown>>> = new Map();
  for (const raw of rawNodes) {
    const type = String(raw.type || 'plant');
    const tier = TIER_MAP[type] ?? 1;
    if (!tierGroups.has(tier)) tierGroups.set(tier, []);
    tierGroups.get(tier)!.push(raw);
  }

  const positioned: GraphNode[] = [];
  for (const [tier, group] of tierGroups) {
    const totalHeight = group.length * ECHELON_Y_GAP;
    const startY = -totalHeight / 2;
    group.forEach((raw, index) => {
      const metrics = (raw.metrics || {}) as GraphNodeData['metrics'];
      const nodeType = String(raw.type || 'plant');
      const isResource = nodeType === 'resource';
      const isCustomer = nodeType === 'customer';
      const reactFlowType = isCustomer ? 'customer' : isResource ? 'resource' : nodeType === 'bom_item' ? 'bom' : 'facility';
      positioned.push({
        id: String(raw.id || `node_${index}`),
        type: reactFlowType,
        position: { x: tier * ECHELON_X_GAP, y: startY + index * ECHELON_Y_GAP },
        data: {
          label: String(raw.label || raw.id || ''),
          type: nodeType,
          status: String(raw.status || 'HEALTHY'),
          metrics: {
            capacity: Number(metrics?.capacity) || 0,
            utilized: Number(metrics?.utilized) || 0,
            utilization_pct: Number(metrics?.utilization_pct) || 0,
            inventory_on_hand: Number(metrics?.inventory_on_hand) || 0,
            efficiency: Number(metrics?.efficiency) || 0,
          },
          coordinates: (raw.coordinates && typeof raw.coordinates === 'object' && 'lat' in raw.coordinates && 'lng' in raw.coordinates) ? raw.coordinates as { lat: number; lng: number } : null,
          depth: Number(raw.depth) || 0,
          is_cycle: Boolean(raw.is_cycle),
          draw_qty_per_unit: Number(raw.draw_qty_per_unit) || 0,
          tier,
        } satisfies GraphNodeData,
      });
    });
  }
  return positioned;
}

function buildEdges(rawEdges: Array<Record<string, unknown>>, _rawNodes: Array<Record<string, unknown>>): FlowEdge[] {
  return rawEdges.map((raw, index) => {
    const data: FlowEdgeData = {
      baseline_volume: Number(raw.baseline_volume) || 0,
      simulated_volume: Number(raw.simulated_volume) || 0,
      delta_volume: Number(raw.delta_volume) || 0,
      transit_time_days: Number(raw.transit_time_days) || 0,
      cost_per_unit: Number(raw.cost_per_unit) || 0,
      is_congested: Boolean(raw.is_congested),
      items: Array.isArray(raw.items) ? raw.items as string[] : [],
      edge_type: String(raw.edge_type || 'flow'),
    };
    const colors = getEdgeColors(data);
    return {
      id: String(raw.id || `edge_${index}`),
      source: String(raw.source || ''),
      target: String(raw.target || ''),
      type: 'animatedFlow',
      data,
      animated: true,
      style: { stroke: colors.stroke, strokeWidth: colors.strokeWidth },
    };
  }).filter((edge) => edge.source && edge.target);
}

function getEdgeColors(data: FlowEdgeData): { stroke: string; strokeWidth: number } {
  const maxVolume = Math.max(data.baseline_volume, data.simulated_volume, 1);
  const normalizedWidth = Math.min(Math.max(data.simulated_volume / maxVolume * 6, 1.5), 8);
  if (data.is_congested) return { stroke: '#dc2626', strokeWidth: Math.max(normalizedWidth, 3) };
  if (data.delta_volume > 0) return { stroke: '#16a34a', strokeWidth: normalizedWidth + 0.5 };
  if (data.delta_volume < 0) return { stroke: '#f59e0b', strokeWidth: normalizedWidth };
  return { stroke: '#3b82f6', strokeWidth: normalizedWidth };
}

function getNodeStatus(utilPct: number): string {
  if (utilPct > 100) return 'BOTTLENECK';
  if (utilPct > 85) return 'WARNING';
  return 'HEALTHY';
}

function statusColor(status: string): string {
  if (status === 'BOTTLENECK') return 'text-red-600 bg-red-50 border-red-200';
  if (status === 'WARNING') return 'text-amber-600 bg-amber-50 border-amber-200';
  return 'text-emerald-600 bg-emerald-50 border-emerald-200';
}

function statusIcon(status: string) {
  if (status === 'BOTTLENECK') return <AlertTriangle className="h-3 w-3" />;
  if (status === 'WARNING') return <Clock className="h-3 w-3" />;
  return <CheckCircle2 className="h-3 w-3" />;
}

function utilBarColor(pct: number): string {
  if (pct >= 100) return 'bg-red-500';
  if (pct >= 85) return 'bg-amber-400';
  if (pct >= 60) return 'bg-blue-500';
  return 'bg-emerald-500';
}

function FacilityNode({ data }: NodeProps<GraphNode>) {
  const d = data as unknown as GraphNodeData;
  const colors = TYPE_COLORS[d.type] || TYPE_COLORS.plant;
  const Icon = TYPE_ICONS[d.type] || Factory;
  const utilPct = d.metrics.utilization_pct || 0;

  return (
    <div className={`relative w-[${NODE_WIDTH}px] rounded-lg border-2 ${colors.border} ${colors.bg} shadow-sm transition-shadow hover:shadow-md`}>
      <Handle type="target" position={Position.Left} className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-slate-400" />
      <div className="px-3 py-2">
        <div className="mb-1.5 flex items-center gap-2">
          <Icon className={`h-4 w-4 ${colors.text}`} />
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase ${colors.badge}`}>
            {d.type}
          </span>
          <span className={`ml-auto flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${statusColor(d.status)}`}>
            {statusIcon(d.status)}
            {d.status}
          </span>
        </div>
        <p className={`truncate text-xs font-bold ${colors.text}`} title={d.label}>
          {d.label}
        </p>
        <div className="mt-2">
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>Utilization</span>
            <span className="font-bold">{utilPct.toFixed(1)}%</span>
          </div>
          <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full transition-all duration-500 ${utilBarColor(utilPct)} ${utilPct >= 100 ? 'animate-pulse' : ''}`}
              style={{ width: `${Math.min(utilPct, 100)}%` }}
            />
          </div>
        </div>
        {d.metrics.inventory_on_hand != null && d.metrics.inventory_on_hand > 0 && (
          <p className="mt-1 text-[10px] text-slate-500">
            Inventory: {(d.metrics.inventory_on_hand ?? 0).toLocaleString()} units
          </p>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-slate-400" />
    </div>
  );
}

function ResourceNode({ data }: NodeProps<GraphNode>) {
  const d = data as unknown as GraphNodeData;
  const colors = TYPE_COLORS.resource;
  const utilPct = d.metrics.utilization_pct || 0;
  const efficiency = d.metrics.efficiency || 1;
  const overtimeSlack = Math.max(0, 100 - utilPct);

  return (
    <div className={`w-[${NODE_WIDTH}px] rounded-lg border-2 ${colors.border} ${colors.bg} shadow-sm transition-shadow hover:shadow-md`}>
      <Handle type="target" position={Position.Left} className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-slate-400" />
      <div className="px-3 py-2">
        <div className="mb-1.5 flex items-center gap-2">
          <Cpu className="h-4 w-4 text-amber-600" />
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase ${colors.badge}`}>
            resource
          </span>
          <span className={`ml-auto flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${statusColor(d.status)}`}>
            {statusIcon(d.status)}
            {d.status}
          </span>
        </div>
        <p className={`truncate text-xs font-bold ${colors.text}`} title={d.label}>
          {d.label}
        </p>
        <div className="mt-2 space-y-1">
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>Active Hours</span>
            <span className="font-bold">{d.metrics.utilized.toFixed(1)} / {d.metrics.capacity.toFixed(1)}h</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full transition-all duration-500 ${utilBarColor(utilPct)} ${utilPct >= 100 ? 'animate-pulse' : ''}`}
              style={{ width: `${Math.min(utilPct, 100)}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-slate-500">Efficiency</span>
            <span className="font-semibold text-slate-700">{(efficiency * 100).toFixed(0)}%</span>
          </div>
          {overtimeSlack < 15 && (
            <div className="flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
              <AlertTriangle className="h-3 w-3" />
              {overtimeSlack < 5 ? 'Critical: no OT slack' : `${overtimeSlack.toFixed(0)}% OT slack remaining`}
            </div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-slate-400" />
    </div>
  );
}

function CustomerNode({ data }: NodeProps<GraphNode>) {
  const d = data as unknown as GraphNodeData;
  const colors = TYPE_COLORS.customer;
  const utilPct = d.metrics.utilization_pct || 0;
  const otif = utilPct > 0 ? Math.min(100, 100 - (utilPct * 0.3)) : 100;

  return (
    <div className={`w-[${NODE_WIDTH}px] rounded-lg border-2 ${colors.border} ${colors.bg} shadow-sm transition-shadow hover:shadow-md`}>
      <Handle type="target" position={Position.Left} className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-slate-400" />
      <div className="px-3 py-2">
        <div className="mb-1.5 flex items-center gap-2">
          <Users className="h-4 w-4 text-rose-600" />
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase ${colors.badge}`}>
            customer
          </span>
          <span className={`ml-auto flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${statusColor(d.status)}`}>
            {statusIcon(d.status)}
            {d.status}
          </span>
        </div>
        <p className={`truncate text-xs font-bold ${colors.text}`} title={d.label}>
          {d.label}
        </p>
        <div className="mt-2 space-y-1">
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>OTIF</span>
            <span className="font-bold">{otif.toFixed(1)}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full transition-all duration-500 ${otif >= 95 ? 'bg-emerald-500' : otif >= 80 ? 'bg-amber-400' : 'bg-red-500'}`}
              style={{ width: `${Math.min(otif, 100)}%` }}
            />
          </div>
          <div className="flex items-center gap-1 text-[10px]">
            {d.status === 'HEALTHY' ? (
              <span className="flex items-center gap-1 font-semibold text-emerald-600"><CheckCircle2 className="h-3 w-3" /> Met</span>
            ) : d.status === 'WARNING' ? (
              <span className="flex items-center gap-1 font-semibold text-amber-600"><Clock className="h-3 w-3" /> Late</span>
            ) : (
              <span className="flex items-center gap-1 font-semibold text-red-600"><AlertTriangle className="h-3 w-3" /> Unmet</span>
            )}
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-slate-400" />
    </div>
  );
}

function BomNode({ data }: NodeProps<GraphNode>) {
  const d = data as unknown as GraphNodeData;
  const colors = TYPE_COLORS.bom_item;
  return (
    <div className={`w-[180px] rounded-lg border-2 ${colors.border} ${colors.bg} shadow-sm`}>
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !rounded-full !border-2 !border-white !bg-slate-400" />
      <div className="px-3 py-2">
        <div className="mb-1 flex items-center gap-1.5">
          <Package className="h-3.5 w-3.5 text-slate-600" />
          {d.is_cycle && <span className="text-[10px] font-bold text-amber-500">CYCLE</span>}
        </div>
        <p className="truncate text-[11px] font-bold text-slate-700" title={d.label}>{d.label}</p>
        {d.draw_qty_per_unit != null && d.draw_qty_per_unit > 0 && (
          <p className="text-[10px] text-slate-500">Qty: {d.draw_qty_per_unit}</p>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !rounded-full !border-2 !border-white !bg-slate-400" />
    </div>
  );
}

function AnimatedFlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, style }: EdgeProps<FlowEdge>) {
  const d = (data || {}) as FlowEdgeData;
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });
  const strokeWidth = Number(style?.strokeWidth) || 2;
  const dashArray = d.edge_type === 'bom' ? '4 4' : '8 4';

  return (
    <g className="react-flow__edge-animated">
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          ...style,
          strokeDasharray: dashArray,
          strokeDashoffset: 0,
        }}
      />
      {d.delta_volume !== 0 && (
        <text
          x={(sourceX + targetX) / 2}
          y={(sourceY + targetY) / 2 - 8}
          className="pointer-events-none select-none"
          textAnchor="middle"
          fill={d.delta_volume > 0 ? '#16a34a' : '#dc2626'}
          fontSize={10}
          fontWeight={700}
        >
          {d.delta_volume > 0 ? '+' : ''}{d.delta_volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </text>
      )}
      {d.transit_time_days > 0 && (
        <text
          x={(sourceX + targetX) / 2}
          y={(sourceY + targetY) / 2 + 12}
          className="pointer-events-none select-none"
          textAnchor="middle"
          fill="#94a3b8"
          fontSize={9}
        >
          {d.transit_time_days}d transit
        </text>
      )}
    </g>
  );
}

function WhatIfDrawer({ node, existingOverride, onApply, onClose }: {
  node: GraphNode;
  existingOverride?: WhatIfOverride;
  onApply: (override: WhatIfOverride) => void;
  onClose: () => void;
}) {
  const d = node.data as unknown as GraphNodeData;
  const colors = TYPE_COLORS[d.type] || TYPE_COLORS.plant;
  const [capacityDelta, setCapacityDelta] = useState(existingOverride?.capacityDelta ?? 0);
  const [leadTimeDelta, setLeadTimeDelta] = useState(existingOverride?.leadTimeDelta ?? 0);

  const projectedUtil = useMemo(() => {
    const factor = 1 + capacityDelta / 100;
    const newCap = Math.max(d.metrics.capacity * factor, 0);
    return newCap > 0 ? (d.metrics.utilized / newCap) * 100 : 0;
  }, [capacityDelta, d.metrics]);

  const handleApply = () => {
    onApply({
      nodeId: node.id,
      nodeLabel: d.label,
      nodeType: d.type,
      capacityDelta,
      leadTimeDelta,
      originalCapacity: d.metrics.capacity,
      originalUtilPct: d.metrics.utilization_pct,
    });
  };

  return (
    <div className="absolute right-0 top-0 z-50 flex h-full w-[340px] flex-col border-l border-slate-200 bg-white shadow-xl animate-slide-in-right">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sliders className="h-4 w-4 text-blue-600" />
          <span className="font-semibold text-slate-800">What-If Override</span>
        </div>
        <button onClick={onClose} className="rounded p-1 hover:bg-slate-100" title="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-auto px-4 py-4">
        <div className={`mb-4 rounded-lg border ${colors.border} ${colors.bg} p-3`}>
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase ${colors.badge}`}>{d.type}</span>
            <span className={`text-xs font-bold ${colors.text}`}>{d.label}</span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-[10px]">
            <div className="rounded bg-white/60 p-1.5">
              <p className="text-slate-500">Capacity</p>
              <p className="font-bold text-slate-800">{d.metrics.capacity.toLocaleString()} units</p>
            </div>
            <div className="rounded bg-white/60 p-1.5">
              <p className="text-slate-500">Utilization</p>
              <p className="font-bold text-slate-800">{d.metrics.utilization_pct.toFixed(1)}%</p>
            </div>
          </div>
        </div>

        <div className="space-y-5">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-700">Capacity Adjustment</label>
              <span className={`rounded px-1.5 py-0.5 text-xs font-bold ${capacityDelta >= 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                {capacityDelta >= 0 ? '+' : ''}{capacityDelta}%
              </span>
            </div>
            <input
              type="range"
              min={-100}
              max={50}
              value={capacityDelta}
              onChange={(e) => setCapacityDelta(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-slate-400">
              <span>-100%</span>
              <span>0%</span>
              <span>+50%</span>
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-700">Lead Time Adjustment</label>
              <span className={`rounded px-1.5 py-0.5 text-xs font-bold ${leadTimeDelta <= 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                {leadTimeDelta >= 0 ? '+' : ''}{leadTimeDelta} days
              </span>
            </div>
            <input
              type="range"
              min={-14}
              max={14}
              value={leadTimeDelta}
              onChange={(e) => setLeadTimeDelta(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-slate-400">
              <span>-14 days</span>
              <span>0</span>
              <span>+14 days</span>
            </div>
          </div>

          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
            <p className="text-[10px] font-semibold uppercase text-blue-600">Projected Impact</p>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <div>
                <p className="text-[10px] text-slate-500">New Utilization</p>
                <p className={`text-sm font-bold ${projectedUtil > 100 ? 'text-red-600' : projectedUtil > 85 ? 'text-amber-600' : 'text-emerald-600'}`}>
                  {projectedUtil.toFixed(1)}%
                </p>
              </div>
              <div>
                <p className="text-[10px] text-slate-500">New Capacity</p>
                <p className="text-sm font-bold text-slate-800">
                  {Math.max(d.metrics.capacity * (1 + capacityDelta / 100), 0).toLocaleString()}
                </p>
              </div>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div
                className={`h-full rounded-full transition-all duration-300 ${utilBarColor(projectedUtil)}`}
                style={{ width: `${Math.min(projectedUtil, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="border-t border-slate-200 px-4 py-3">
        <button
          onClick={handleApply}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
        >
          <ArrowRight className="h-4 w-4" />
          Apply What-If
        </button>
        <p className="mt-2 text-center text-[10px] text-slate-400">Triggers instant graph re-render with updated flows</p>
      </div>
    </div>
  );
}

function LegendBar() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-2 text-[10px]">
      <span className="font-semibold text-slate-600">Legend:</span>
      {[
        { color: 'bg-violet-400', label: 'Supplier' },
        { color: 'bg-blue-400', label: 'Plant' },
        { color: 'bg-amber-400', label: 'Resource' },
        { color: 'bg-emerald-400', label: 'DC' },
        { color: 'bg-rose-400', label: 'Customer' },
      ].map(({ color, label }) => (
        <span key={label} className="flex items-center gap-1">
          <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
          {label}
        </span>
      ))}
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 border-t-2 border-dashed border-blue-500" />
        Normal
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 border-t-2 border-dashed border-green-500" />
        Volume Increase
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 border-t-2 border-dashed border-red-500" />
        Congested
      </span>
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <span className="flex items-center gap-1">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        &le;85%
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2 w-2 rounded-full bg-amber-400" />
        85-100%
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
        &ge;100%
      </span>
    </div>
  );
}
