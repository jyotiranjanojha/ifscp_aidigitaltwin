'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ScatterplotLayer, ArcLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, PickingInfo } from '@deck.gl/core';
import { MapboxOverlay } from '@deck.gl/mapbox';
import maplibregl from 'maplibre-gl';
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Filter,
  Globe,
  Layers,
  Plane,
  Power,
  RotateCcw,
  Ship,
  X,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
const MAP_STYLE = process.env.NEXT_PUBLIC_MAPLIBRE_STYLE_URL || 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

const STATUS_COLORS: Record<string, [number, number, number, number]> = {
  HEALTHY: [16, 185, 129, 220],
  WARNING: [245, 158, 11, 220],
  BOTTLENECK: [239, 68, 68, 240],
};

const NODE_TYPE_COLORS: Record<string, [number, number, number, number]> = {
  supplier: [139, 92, 246, 220],
  plant: [59, 130, 246, 220],
  resource: [245, 158, 11, 200],
  dc: [16, 185, 129, 220],
  customer: [244, 63, 94, 220],
};

const NODE_TYPE_RADIUS: Record<string, number> = {
  supplier: 18000,
  plant: 22000,
  resource: 12000,
  dc: 20000,
  customer: 16000,
};

interface GeoNode {
  id: string;
  label: string;
  type: string;
  status: string;
  coordinates: { lat: number; lng: number } | null;
  metrics: {
    capacity: number;
    utilized: number;
    utilization_pct: number;
    inventory_on_hand?: number;
  };
}

interface GeoEdge {
  id: string;
  source: string;
  target: string;
  baseline_volume: number;
  simulated_volume: number;
  delta_volume: number;
  transit_time_days: number;
  cost_per_unit: number;
  is_congested: boolean;
  items?: string[];
  edge_type?: string;
  source_coords?: { lat: number; lng: number } | null;
  target_coords?: { lat: number; lng: number } | null;
  source_label?: string;
  target_label?: string;
}

interface DisruptionSimulation {
  targetType: 'facility' | 'lane';
  targetId: string;
  targetLabel: string;
  disruptionType: string;
  capacityReduction: number;
}

interface GeoSpatialFlowTwinProps {
  scenarioId?: string;
  focusNodeId?: string;
  focusLabel?: string;
  onDisruptionApply?: (sim: DisruptionSimulation) => void;
}

export default function GeoSpatialFlowTwin({ scenarioId = 'baseline', focusNodeId, focusLabel, onDisruptionApply }: GeoSpatialFlowTwinProps) {
  const [nodes, setNodes] = useState<GeoNode[]>([]);
  const [edges, setEdges] = useState<GeoEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);

  const [showBottlenecksOnly, setShowBottlenecksOnly] = useState(false);
  const [showActiveDisruptions, setShowActiveDisruptions] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [hoveredInfo, setHoveredInfo] = useState<PickingInfo | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: GeoNode | GeoEdge; itemType: 'facility' | 'lane' } | null>(null);
  const [disruptions, setDisruptions] = useState<Map<string, DisruptionSimulation>>(new Map());

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [20, 25],
      zoom: 1.8,
      pitch: 45,
      bearing: 0,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      getTooltip: null,
      onClick: (info) => {
        if (!info?.object) return;
        const obj = info.object as GeoNode | GeoEdge;
        if ('baseline_volume' in obj) {
          setContextMenu({ x: info.x, y: info.y, item: obj as GeoEdge, itemType: 'lane' });
        } else if ('coordinates' in obj) {
          setContextMenu({ x: info.x, y: info.y, item: obj as GeoNode, itemType: 'facility' });
        }
      },
      onHover: (info) => setHoveredInfo(info),
    });
    map.addControl(overlay as unknown as maplibregl.IControl);

    mapRef.current = map;
    overlayRef.current = overlay;

    return () => {
      overlay.finalize();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

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

        const geoNodes: GeoNode[] = (data.nodes || []).filter((n: GeoNode) => n.coordinates);
        const coordMap = new Map(geoNodes.map((n) => [n.id, n.coordinates]));
        const geoEdges: GeoEdge[] = (data.edges || [])
          .filter((e: GeoEdge) => e.edge_type !== 'bom')
          .map((e: GeoEdge) => ({
            ...e,
            source_coords: coordMap.get(e.source) || null,
            target_coords: coordMap.get(e.target) || null,
            source_label: geoNodes.find((n) => n.id === e.source)?.label || e.source,
            target_label: geoNodes.find((n) => n.id === e.target)?.label || e.target,
          }))
          .filter((e: GeoEdge) => e.source_coords && e.target_coords);

        setNodes(geoNodes);
        setEdges(geoEdges);
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
    if (!focusNodeId || !mapRef.current || !nodes.length) return;
    const match = nodes.find((n) => n.id === focusNodeId || n.label.toLowerCase() === focusLabel?.toLowerCase());
    if (match?.coordinates) {
      mapRef.current.flyTo({ center: [match.coordinates.lng, match.coordinates.lat], zoom: 5, pitch: 45, duration: 800 });
    }
  }, [focusNodeId, focusLabel, nodes]);

  const filteredEdges = useMemo(() => {
    let result = edges;
    if (showBottlenecksOnly) result = result.filter((e) => e.is_congested || e.delta_volume < 0);
    if (showActiveDisruptions) result = result.filter((e) => disruptions.has(e.id) || e.is_congested);
    return result;
  }, [edges, showBottlenecksOnly, showActiveDisruptions, disruptions]);

  const filteredNodes = useMemo(() => {
    if (!showBottlenecksOnly && !showActiveDisruptions) return nodes;
    if (showBottlenecksOnly) {
      const bottleneckIds = new Set(nodes.filter((n) => n.status === 'BOTTLENECK' || n.status === 'WARNING').map((n) => n.id));
      const connectedEdges = filteredEdges.filter((e) => bottleneckIds.has(e.source) || bottleneckIds.has(e.target));
      const connectedIds = new Set(connectedEdges.flatMap((e) => [e.source, e.target]));
      return nodes.filter((n) => bottleneckIds.has(n.id) || connectedIds.has(n.id));
    }
    return nodes;
  }, [nodes, filteredEdges, showBottlenecksOnly, showActiveDisruptions]);

  const getArcColor = useCallback((edge: GeoEdge): [number, number, number, number] => {
    if (edge.is_congested) return [239, 68, 68, 200];
    if (disruptions.has(edge.id)) return [239, 68, 68, 220];
    if (compareMode && edge.delta_volume > 0) return [34, 211, 238, 200];
    if (compareMode && edge.delta_volume < 0) return [251, 191, 36, 180];
    return [100, 116, 139, 120];
  }, [compareMode, disruptions]);

  const getArcWidth = useCallback((edge: GeoEdge): number => {
    const maxVol = Math.max(edge.baseline_volume, edge.simulated_volume, 1);
    const normalized = Math.max((edge.simulated_volume / maxVol) * 6, 1.5);
    return edge.is_congested ? Math.max(normalized, 4) : normalized;
  }, []);

  const layers: Layer[] = useMemo(() => {
    const arcLayer = new ArcLayer({
      id: 'flow-arcs',
      data: filteredEdges,
      getSourcePosition: (d: GeoEdge) => [d.source_coords!.lng, d.source_coords!.lat],
      getTargetPosition: (d: GeoEdge) => [d.target_coords!.lng, d.target_coords!.lat],
      getSourceColor: (d: GeoEdge) => getArcColor(d),
      getTargetColor: (d: GeoEdge) => {
        const c = getArcColor(d);
        return [c[0], c[1], c[2], Math.min(c[3], 160)];
      },
      getWidth: (d: GeoEdge) => getArcWidth(d),
      greatCircle: true,
      pickable: true,
      widthMinPixels: 1,
      widthMaxPixels: 12,
    });

    const scatterLayer = new ScatterplotLayer({
      id: 'facility-pins',
      data: filteredNodes,
      getPosition: (d: GeoNode) => [d.coordinates!.lng, d.coordinates!.lat],
      getRadius: (d: GeoNode) => {
        const base = NODE_TYPE_RADIUS[d.type] || 15000;
        const volFactor = Math.min(d.metrics.utilized / Math.max(d.metrics.capacity, 1), 2);
        return base * (0.8 + volFactor * 0.4);
      },
      getFillColor: (d: GeoNode) => STATUS_COLORS[d.status] || STATUS_COLORS.HEALTHY,
      getLineColor: (d: GeoNode) => NODE_TYPE_COLORS[d.type] || [59, 130, 246, 255],
      lineWidthMinPixels: 2,
      lineWidthMaxPixels: 4,
      pickable: true,
      radiusMinPixels: 6,
      radiusMaxPixels: 24,
      stroked: true,
      filled: true,
      parameters: { depthTest: true },
    });

    const labelLayer = new TextLayer({
      id: 'node-labels',
      data: filteredNodes.filter((n) => n.status === 'BOTTLENECK' || n.type === 'customer' || n.type === 'supplier'),
      getPosition: (d: GeoNode) => [d.coordinates!.lng, d.coordinates!.lat],
      getText: (d: GeoNode) => d.label.length > 18 ? d.label.slice(0, 16) + '...' : d.label,
      getSize: 10,
      getColor: [30, 41, 59, 220],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'bottom',
      getPixelOffset: [0, -14],
      pickable: false,
    });

    return [arcLayer, scatterLayer, labelLayer];
  }, [filteredNodes, filteredEdges, getArcColor, getArcWidth]);

  useEffect(() => {
    overlayRef.current?.setProps({ layers });
  }, [layers]);

  const handleDisruption = useCallback((type: string, target: GeoNode | GeoEdge, itemType: 'facility' | 'lane') => {
    const sim: DisruptionSimulation = {
      targetType: itemType,
      targetId: target.id,
      targetLabel: (target as GeoNode).label || (target as GeoEdge).source_label || target.id,
      disruptionType: type,
      capacityReduction: type === 'port_strike' || type === 'supplier_outage' ? -100 : -50,
    };
    setDisruptions((prev) => {
      const next = new Map(prev);
      next.set(target.id, sim);
      return next;
    });
    setContextMenu(null);
    onDisruptionApply?.(sim);
  }, [onDisruptionApply]);

  const clearDisruptions = useCallback(() => {
    setDisruptions(new Map());
  }, []);

  const tooltipContent = useMemo(() => {
    if (!hoveredInfo?.object) return null;
    const obj = hoveredInfo.object as GeoNode | GeoEdge;
    if ('baseline_volume' in obj) {
      const edge = obj as GeoEdge;
      return (
        <div className="pointer-events-none max-w-xs rounded-lg border border-slate-200 bg-white p-3 shadow-xl">
          <p className="text-xs font-bold text-slate-800">
            {edge.source_label} &rarr; {edge.target_label}
          </p>
          <div className="mt-2 space-y-1 text-[11px]">
            <div className="flex justify-between"><span className="text-slate-500">Baseline Volume</span><span className="font-semibold">{edge.baseline_volume.toLocaleString()}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Simulated Volume</span><span className="font-semibold">{edge.simulated_volume.toLocaleString()}</span></div>
            {edge.delta_volume !== 0 && (
              <div className="flex justify-between">
                <span className="text-slate-500">Delta</span>
                <span className={`font-bold ${edge.delta_volume > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                  {edge.delta_volume > 0 ? '+' : ''}{edge.delta_volume.toLocaleString()}
                </span>
              </div>
            )}
            <div className="flex justify-between"><span className="text-slate-500">Transit Days</span><span className="font-semibold">{edge.transit_time_days}d</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Cost/Unit</span><span className="font-semibold">${edge.cost_per_unit.toFixed(2)}</span></div>
            {edge.items && edge.items.length > 0 && (
              <div className="mt-1 truncate text-slate-400">Items: {edge.items.join(', ')}</div>
            )}
            {edge.is_congested && (
              <div className="mt-1 flex items-center gap-1 font-bold text-red-600">
                <AlertTriangle className="h-3 w-3" /> CONGESTED
              </div>
            )}
          </div>
        </div>
      );
    }
    const node = obj as GeoNode;
    return (
      <div className="pointer-events-none max-w-xs rounded-lg border border-slate-200 bg-white p-3 shadow-xl">
        <div className="flex items-center gap-2">
          <span className="rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase" style={{ backgroundColor: `rgb(${NODE_TYPE_COLORS[node.type]?.slice(0, 3).join(',')})`, color: 'white' }}>
            {node.type}
          </span>
          <span className="text-xs font-bold text-slate-800">{node.label}</span>
        </div>
        <div className="mt-2 space-y-1 text-[11px]">
          <div className="flex justify-between"><span className="text-slate-500">Capacity</span><span className="font-semibold">{node.metrics.capacity.toLocaleString()}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Utilized</span><span className="font-semibold">{node.metrics.utilized.toLocaleString()}</span></div>
          <div className="flex justify-between">
            <span className="text-slate-500">Utilization</span>
            <span className={`font-bold ${node.metrics.utilization_pct > 100 ? 'text-red-600' : node.metrics.utilization_pct > 85 ? 'text-amber-600' : 'text-emerald-600'}`}>
              {node.metrics.utilization_pct.toFixed(1)}%
            </span>
          </div>
          <div className="mt-1 flex items-center gap-1">
            {node.status === 'HEALTHY' ? <CheckCircle2 className="h-3 w-3 text-emerald-500" /> : <AlertTriangle className="h-3 w-3 text-amber-500" />}
            <span className={`font-semibold ${node.status === 'BOTTLENECK' ? 'text-red-600' : node.status === 'WARNING' ? 'text-amber-600' : 'text-emerald-600'}`}>{node.status}</span>
          </div>
        </div>
      </div>
    );
  }, [hoveredInfo]);

  if (loading) {
    return (
      <div className="flex h-[600px] items-center justify-center rounded-lg border border-slate-200 bg-white">
        <div className="text-center">
          <Globe className="mx-auto h-8 w-8 animate-pulse text-blue-500" />
          <p className="mt-3 text-sm font-medium text-slate-600">Loading geospatial topology...</p>
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
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">2.5D Geospatial Flow Map</h2>
          <p className="text-sm text-slate-500">Global transportation lanes with 3D arc visualization</p>
        </div>
        {summary && (
          <div className="flex gap-3 text-xs">
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
              {filteredNodes.length} nodes
            </span>
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
              {filteredEdges.length} lanes
            </span>
            {(summary.congested_edges as number) > 0 && (
              <span className="rounded-md bg-red-100 px-2 py-1 font-medium text-red-700">
                {(summary.congested_edges as number)} congested
              </span>
            )}
            {disruptions.size > 0 && (
              <button onClick={clearDisruptions} className="inline-flex items-center gap-1 rounded-md bg-amber-100 px-2 py-1 font-medium text-amber-700 hover:bg-amber-200">
                <RotateCcw className="h-3 w-3" /> Clear {disruptions.size} disruption{disruptions.size > 1 ? 's' : ''}
              </button>
            )}
          </div>
        )}
      </div>

      <LayerControlPanel
        showBottlenecksOnly={showBottlenecksOnly}
        setShowBottlenecksOnly={setShowBottlenecksOnly}
        showActiveDisruptions={showActiveDisruptions}
        setShowActiveDisruptions={setShowActiveDisruptions}
        compareMode={compareMode}
        setCompareMode={setCompareMode}
      />

      <div className="relative h-[600px] overflow-hidden rounded-lg border border-slate-200">
        <div ref={mapContainerRef} className="absolute inset-0" />

        <div className="absolute left-4 top-4 z-10 flex items-center gap-2 rounded-md bg-white/90 px-2.5 py-1.5 shadow-sm">
          <Globe className="h-4 w-4 text-slate-600" />
          <span className="text-xs font-semibold text-slate-700">2.5D Globe</span>
        </div>

        {hoveredInfo && tooltipContent && (
          <div
            className="pointer-events-none absolute z-20"
            style={{ left: (hoveredInfo as PickingInfo & { x: number; y: number }).x + 12, top: (hoveredInfo as PickingInfo & { x: number; y: number }).y - 8 }}
          >
            {tooltipContent}
          </div>
        )}

        {contextMenu && (
          <ContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            target={contextMenu.item}
            itemType={contextMenu.itemType}
            onSelect={(type) => handleDisruption(type, contextMenu.item, contextMenu.itemType)}
            onClose={() => setContextMenu(null)}
          />
        )}
      </div>

      <ArcLegend />
    </div>
  );
}

function LayerControlPanel({ showBottlenecksOnly, setShowBottlenecksOnly, showActiveDisruptions, setShowActiveDisruptions, compareMode, setCompareMode }: {
  showBottlenecksOnly: boolean;
  setShowBottlenecksOnly: (v: boolean) => void;
  showActiveDisruptions: boolean;
  setShowActiveDisruptions: (v: boolean) => void;
  compareMode: boolean;
  setCompareMode: (v: boolean) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <span className="flex items-center gap-1 text-xs font-semibold text-slate-600">
        <Layers className="h-3.5 w-3.5" /> Layers:
      </span>
      <ToggleButton active={showBottlenecksOnly} onClick={() => setShowBottlenecksOnly(!showBottlenecksOnly)}>
        <Filter className="h-3 w-3" /> Bottlenecks Only
      </ToggleButton>
      <ToggleButton active={showActiveDisruptions} onClick={() => setShowActiveDisruptions(!showActiveDisruptions)}>
        <Power className="h-3 w-3" /> Active Disruptions
      </ToggleButton>
      <ToggleButton active={compareMode} onClick={() => setCompareMode(!compareMode)}>
        <Eye className="h-3 w-3" /> Baseline vs What-If
      </ToggleButton>
    </div>
  );
}

function ToggleButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-semibold transition ${active ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}
    >
      {children}
    </button>
  );
}

function ContextMenu({ x, y, target, itemType, onSelect, onClose }: {
  x: number;
  y: number;
  target: GeoNode | GeoEdge;
  itemType: 'facility' | 'lane';
  onSelect: (type: string) => void;
  onClose: () => void;
}) {
  const facilityOptions = [
    { type: 'supplier_outage', label: 'Supplier Outage (-100%)', icon: Power },
    { type: 'port_strike', label: 'Port Strike (-100%)', icon: Ship },
    { type: 'capacity_reduction', label: 'Capacity Cut (-50%)', icon: AlertTriangle },
  ];
  const laneOptions = [
    { type: 'lane_disruption', label: 'Lane Disrupted (-100%)', icon: Plane },
    { type: 'port_strike', label: 'Port Strike (-100%)', icon: Ship },
    { type: 'capacity_reduction', label: 'Lane Congested (-50%)', icon: AlertTriangle },
  ];
  const options = itemType === 'facility' ? facilityOptions : laneOptions;
  const label = (target as GeoNode).label || (target as GeoEdge).source_label || target.id;

  return (
    <>
      <div className="fixed inset-0 z-30" onClick={onClose} />
      <div
        className="absolute z-40 w-64 rounded-lg border border-slate-200 bg-white shadow-xl"
        style={{ left: Math.min(x, window.innerWidth - 280), top: Math.min(y, window.innerHeight - 200) }}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <div className="min-w-0">
            <p className="text-[10px] uppercase text-slate-400">Simulate Disruption</p>
            <p className="truncate text-xs font-bold text-slate-800">{label}</p>
          </div>
          <button onClick={onClose} className="rounded p-0.5 hover:bg-slate-100"><X className="h-3 w-3" /></button>
        </div>
        <div className="p-1.5">
          {options.map((opt) => (
            <button
              key={opt.type}
              onClick={() => onSelect(opt.type)}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-slate-700 hover:bg-red-50 hover:text-red-700 transition"
            >
              <opt.icon className="h-3.5 w-3.5 shrink-0" />
              {opt.label}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

function ArcLegend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-2 text-[10px]">
      <span className="font-semibold text-slate-600">Legend:</span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 rounded bg-slate-400" />
        Normal Flow
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 rounded bg-cyan-400" />
        Volume Increase
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 rounded bg-amber-400" />
        Volume Decrease
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 rounded bg-red-500" />
        Congested
      </span>
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <span className="flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-full bg-violet-500" />
        Supplier
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-full bg-blue-500" />
        Plant
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
        DC
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
        Customer
      </span>
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <span className="text-slate-400">Right-click to simulate disruptions</span>
    </div>
  );
}
