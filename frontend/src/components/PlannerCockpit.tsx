'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Download,
  FileCheck2,
  PackageOpen,
  Play,
  Plus,
  RefreshCw,
  Route,
  SlidersHorizontal,
  Table2,
  UploadCloud,
  Wrench,
  X,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import DualSolverComparator from '@/src/components/DualSolverComparator';
import SolverSelector from '@/src/components/SolverSelector';
import SupplyChainGraphTwin from '@/src/components/visualization/SupplyChainGraphTwin';
import GeoSpatialFlowTwinLoader from '@/src/components/visualization/GeoSpatialFlowTwinLoader';
import {
  exportByPatchPack,
  isCompareResult,
  numberValue,
  runSimulation,
  type BottleneckDiagnostic,
  type RunSimulationResult,
  type ScenarioDelta,
  type SolverResult,
  type SolverType,
} from '@/src/services/simulationApi';

const ALL_ENTITIES = [
  'sourcing', 'sku', 'locations', 'items', 'network', 'calendars',
  'calpattern', 'calattribute', 'customer', 'customerorder', 'dfutoskufcst',
  'inventory', 'skueffinventoryparam', 'schedrcpts', 'supersession',
  'billofmaterials', 'altbillofmaterials', 'productionmethod', 'productionstep',
  'altproductionstep', 'res', 'purchmethod',
];

const ENTITY_LABELS: Record<string, string> = {
  sourcing: 'Sourcing', sku: 'SKU', locations: 'Locations', items: 'Items', network: 'Network', calendars: 'Calendars',
  calpattern: 'Cal Pattern', calattribute: 'Cal Attribute', customer: 'Customer', customerorder: 'Orders', dfutoskufcst: 'Forecast',
  inventory: 'Inventory', skueffinventoryparam: 'Inv Params', schedrcpts: 'Receipts', supersession: 'Supersession',
  billofmaterials: 'BOM', altbillofmaterials: 'Alt BOM', productionmethod: 'Prod Method', productionstep: 'Prod Step',
  altproductionstep: 'Alt Step', res: 'Resources', purchmethod: 'Purchase',
};

const OVERRIDE_TYPES = {
  sourcing: {
    label: 'Sourcing Capacity',
    keyLabel: 'ITEM|SOURCE',
    placeholder: '100000002013|1006',
    valueLabel: 'Reduction',
    valueHint: '0.3 = reduce 30%',
  },
  res: {
    label: 'Resource Capacity',
    keyLabel: 'RES|LOC',
    placeholder: 'FAB_LINE_1|1006',
    valueLabel: 'Reduction',
    valueHint: '0.15 = reduce 15%',
  },
  dfutoskufcst: {
    label: 'Forecast Demand',
    keyLabel: 'ITEM|SKULOC',
    placeholder: '100000002013|VF',
    valueLabel: 'Multiplier',
    valueHint: '1.2 = plus 20%',
  },
} as const;

type RiskOverrides = Record<string, Record<string, number>>;

interface RiskDraft {
  type: keyof typeof OVERRIDE_TYPES;
  key: string;
  value: string;
}

interface MitigationToggles {
  overtime: boolean;
  expedite: boolean;
  altBom: boolean;
}

type VizTab = 'dag' | 'geo' | 'table';

export default function PlannerCockpit() {
  const [files, setFiles] = useState<Record<string, File>>({});
  const [fileErrors, setFileErrors] = useState<Record<string, string>>({});
  const [riskOverrides, setRiskOverrides] = useState<RiskOverrides>({ sourcing: {}, res: {}, dfutoskufcst: {} });
  const [draft, setDraft] = useState<RiskDraft>({ type: 'sourcing', key: '', value: '' });
  const [mitigations, setMitigations] = useState<MitigationToggles>({ overtime: false, expedite: false, altBom: false });
  const [solverType, setSolverType] = useState<SolverType>('heuristic');
  const [results, setResults] = useState<RunSimulationResult | null>(null);
  const [selectedDiagnostic, setSelectedDiagnostic] = useState<BottleneckDiagnostic | null>(null);
  const [lastBenchmarks, setLastBenchmarks] = useState<{ heuristic?: number; lpopt?: number }>({});
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [vizTab, setVizTab] = useState<VizTab>('dag');
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [focusLabel, setFocusLabel] = useState<string | null>(null);

  const uploadedCount = Object.keys(files).length;
  const missingEntities = ALL_ENTITIES.filter((entity) => !files[entity]);
  const isReady = missingEntities.length === 0;
  const activeType = OVERRIDE_TYPES[draft.type];
  const manualDeltas = useMemo(() => buildScenarioDeltas(riskOverrides), [riskOverrides]);
  const mitigationDeltas = useMemo(() => buildMitigationDeltas(mitigations, selectedDiagnostic), [mitigations, selectedDiagnostic]);
  const scenarioDeltas = useMemo(() => [...manualDeltas, ...mitigationDeltas], [manualDeltas, mitigationDeltas]);
  const selectedResult = useMemo(() => primaryResult(results), [results]);
  const diagnostics = useMemo(() => buildDiagnostics(selectedResult), [selectedResult]);
  const impact = useMemo(() => buildImpact(results, scenarioDeltas), [results, scenarioDeltas]);
  const waterfallData = useMemo(() => buildWaterfallData(results), [results]);

  const handleFocusNode = useCallback((nodeId: string, label?: string) => {
    setFocusNodeId(nodeId);
    setFocusLabel(label || null);
    setVizTab((prev) => (prev === 'table' ? 'dag' : prev));
  }, []);

  const handleOverrideFromGraph = useCallback((overrides: Array<{ nodeId: string; capacityDelta: number }>) => {
    const next: RiskOverrides = { sourcing: { ...riskOverrides.sourcing }, res: { ...riskOverrides.res }, dfutoskufcst: { ...riskOverrides.dfutoskufcst } };
    for (const o of overrides) {
      const pct = o.capacityDelta / 100;
      if (o.nodeId.includes('|')) {
        next.sourcing[o.nodeId] = pct;
      } else {
        next.res[o.nodeId] = pct;
      }
    }
    setRiskOverrides(next);
  }, [riskOverrides]);

  const processFiles = useCallback((fileList: File[]) => {
    const accepted: Record<string, File> = {};
    const errors: Record<string, string> = {};

    fileList.forEach((file) => {
      const entity = extractEntityFromFilename(file.name);
      if (!entity) {
        errors[file.name] = 'Expected if_snop_<entity>-<timestamp>.csv';
      } else if (!ALL_ENTITIES.includes(entity)) {
        errors[file.name] = `Unknown entity ${entity}`;
      } else {
        accepted[entity] = file;
      }
    });

    setFiles((prev) => ({ ...prev, ...accepted }));
    setFileErrors(errors);
  }, []);

  const handleRunSimulation = async () => {
    if (!isReady || loading) return;
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const data = await runSimulation({ files, solver_type: solverType, scenario_deltas: scenarioDeltas, risk_adjustments: riskOverrides });
      setResults(data);
      setLastBenchmarks(extractBenchmarks(data));
      setSelectedDiagnostic(buildDiagnostics(primaryResult(data))[0] || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Simulation failed');
    } finally {
      setLoading(false);
    }
  };

  const addOverride = () => {
    const value = Number(draft.value);
    if (!draft.key || !isValidOverrideValue(draft.type, value)) return;
    setRiskOverrides((prev) => ({
      ...prev,
      [draft.type]: { ...prev[draft.type], [normalizeOverrideKey(draft.key)]: value },
    }));
    setDraft({ type: 'sourcing', key: '', value: '' });
  };

  const removeOverride = (type: string, key: string) => {
    setRiskOverrides((prev) => {
      const next = { ...prev, [type]: { ...prev[type] } };
      delete next[type][key];
      return next;
    });
  };

  const handleQuickMitigate = () => {
    if (!selectedDiagnostic) return;
    setMitigations((prev) => ({
      overtime: prev.overtime || selectedDiagnostic.root_cause.includes('CAPACITY'),
      expedite: prev.expedite || selectedDiagnostic.root_cause.includes('SOURCING') || selectedDiagnostic.root_cause.includes('LEAD'),
      altBom: prev.altBom || selectedDiagnostic.root_cause.includes('MATERIAL'),
    }));
  };

  const handleExport = async () => {
    if (!results) return;
    setExporting(true);
    setError(null);
    try {
      const blob = await exportByPatchPack({ files, scenario_deltas: scenarioDeltas, financial_impact: impact });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'planner_what_if_by_patch.zip';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-5 lg:px-6">
        <header className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Planner Decision Cockpit</h1>
              <p className="mt-1 text-sm text-slate-500">Load BY files, choose a solver, test mitigations, and export a production-ready patch pack.</p>
            </div>
            <div className="w-full space-y-3 lg:w-auto lg:min-w-[520px]">
              <SolverSelector solverType={solverType} onChange={setSolverType} heuristicSeconds={lastBenchmarks.heuristic} lpoptSeconds={lastBenchmarks.lpopt} disabled={loading} />
              <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-600">
                <div className="text-sm text-slate-600">
                  <span className="font-semibold text-slate-800">Baseline run is allowed.</span> Overrides are optional after all 22 files are loaded.
                  {solverType === 'compare_both' && <span className="block text-blue-600">Compare runs Heuristic and LpOpt, then shows side-by-side analysis.</span>}
                </div>
              </div>
            </div>
          </div>
          <FlowStatus uploadedCount={uploadedCount} isReady={isReady} hasRun={Boolean(results)} hasDeltas={scenarioDeltas.length > 0} />
        </header>

        {error && <AlertBox message={error} />}

        <section className="grid gap-4 lg:grid-cols-[1fr_380px]">
          <Panel title="Input Pack" icon={UploadCloud} action={<span className="text-sm font-medium text-slate-500">{uploadedCount}/22 files</span>}>
            <DropZone onFiles={processFiles} />
            <FileGrid files={files} onRemove={(entity) => setFiles((prev) => withoutKey(prev, entity))} />
            {Object.keys(fileErrors).length > 0 && <ErrorList errors={fileErrors} />}
          </Panel>

          <Panel title="Simulation Controls" icon={SlidersHorizontal}>
            <OverrideEditor draft={draft} setDraft={setDraft} activeType={activeType} onAdd={addOverride} />
            <OverrideList overrides={riskOverrides} onRemove={removeOverride} />
            {!isReady && <p className="mt-2 text-xs text-red-600">Upload all required files before running.</p>}
            {isReady && !scenarioDeltas.length && <p className="mt-2 text-xs text-slate-500">No overrides selected. This will run the baseline data pack.</p>}
            {isReady && solverType === 'compare_both' && <p className="mt-2 text-xs text-blue-600">Compare mode runs Heuristic and LpOpt, then opens the side-by-side analysis below.</p>}
          </Panel>
        </section>

        <MitigationToolbar mitigations={mitigations} setMitigations={setMitigations} />

        <RunSolverAction
          solverType={solverType}
          isReady={isReady}
          loading={loading}
          missingCount={missingEntities.length}
          onRun={handleRunSimulation}
        />

        <Panel title="Decision Dashboard" icon={BarChart3} action={<button onClick={() => setExportOpen(true)} disabled={!results} className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"><Download className="h-4 w-4" /> Export</button>}>
          <SolverExecutionBanner solverType={solverType} result={results} isReady={isReady} />
          {isCompareResult(results) && solverType === 'compare_both' ? (
            <DualSolverComparator result={results} />
          ) : results && selectedResult ? (
            <DashboardBody result={selectedResult} waterfallData={waterfallData} diagnostics={diagnostics} impact={impact} selectedDiagnostic={selectedDiagnostic} onSelectDiagnostic={(row) => { setSelectedDiagnostic(row); handleFocusNode(row.bottleneck_entity, row.item); }} onQuickMitigate={handleQuickMitigate} />
          ) : (
            <EmptyState ready={isReady} />
          )}
        </Panel>

        <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
            <h2 className="text-base font-semibold text-slate-800">Supply Chain Visualizations</h2>
            {focusNodeId && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700">
                Focused: {focusLabel || focusNodeId}
                <button onClick={() => { setFocusNodeId(null); setFocusLabel(null); }} className="rounded-full p-0.5 hover:bg-blue-100"><X className="h-3 w-3" /></button>
              </span>
            )}
          </div>

          <div className="flex gap-1 border-b border-slate-200 px-4 pt-2">
            <VizTabButton active={vizTab === 'dag'} onClick={() => setVizTab('dag')} icon={GitBranchIcon}>Topology DAG View</VizTabButton>
            <VizTabButton active={vizTab === 'geo'} onClick={() => setVizTab('geo')} icon={Route}>2.5D Geo Flow Map</VizTabButton>
            <VizTabButton active={vizTab === 'table'} onClick={() => setVizTab('table')} icon={Table2}>Tabular Demand Waterfall</VizTabButton>
          </div>

          <div className="p-4">
            {vizTab === 'dag' && (
              <SupplyChainGraphTwin
                scenarioId="baseline"
                focusNodeId={focusNodeId || undefined}
                focusLabel={focusLabel || undefined}
                onOverrideApply={handleOverrideFromGraph}
              />
            )}
            {vizTab === 'geo' && (
              <GeoSpatialFlowTwinLoader
                scenarioId="baseline"
                focusNodeId={focusNodeId || undefined}
                focusLabel={focusLabel || undefined}
                onDisruptionApply={() => {}}
              />
            )}
            {vizTab === 'table' && results && selectedResult && (
              <DemandWaterfallTab
                waterfallData={waterfallData}
                impact={impact}
                diagnostics={diagnostics}
                selectedDiagnostic={selectedDiagnostic}
                onSelectDiagnostic={(row) => { setSelectedDiagnostic(row); handleFocusNode(row.bottleneck_entity, row.item); }}
                onQuickMitigate={handleQuickMitigate}
              />
            )}
            {vizTab === 'table' && (!results || !selectedResult) && (
              <EmptyWaterfallState ready={isReady} hasRun={Boolean(results)} />
            )}
          </div>
        </section>

        {exportOpen && <ExportModal deltas={scenarioDeltas} impact={impact} exporting={exporting} onClose={() => setExportOpen(false)} onExport={handleExport} />}
      </div>
    </div>
  );
}

function VizTabButton({ active, onClick, icon: Icon, children }: { active: boolean; onClick: () => void; icon: React.FC<{ className?: string }>; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold transition ${active ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {children}
    </button>
  );
}

function GitBranchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="6" x2="6" y1="3" y2="15" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  );
}

function DemandWaterfallTab({ waterfallData, impact, diagnostics, selectedDiagnostic, onSelectDiagnostic, onQuickMitigate }: {
  waterfallData: Array<Record<string, number | string>>;
  impact: Record<string, number>;
  diagnostics: BottleneckDiagnostic[];
  selectedDiagnostic: BottleneckDiagnostic | null;
  onSelectDiagnostic: (row: BottleneckDiagnostic) => void;
  onQuickMitigate: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Kpi label="Revenue Protected" value={formatCurrency(impact.protectedRevenue)} />
        <Kpi label="SLA / OTIF" value={`${impact.otif.toFixed(2)}%`} />
        <Kpi label="Mitigation Cost" value={formatCurrency(impact.mitigationCost)} />
        <Kpi label="ROI" value={`${impact.roi.toFixed(2)}x`} />
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={waterfallData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="scenario" />
            <YAxis />
            <Tooltip formatter={(value) => Number(value).toLocaleString()} />
            <Legend />
            <Bar dataKey="Met" stackId="a" fill="#16a34a" />
            <Bar dataKey="Late Met" stackId="a" fill="#f59e0b" />
            <Bar dataKey="Unmet" stackId="a" fill="#dc2626" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <BottleneckTable diagnostics={diagnostics} selected={selectedDiagnostic} onSelect={onSelectDiagnostic} onQuickMitigate={onQuickMitigate} />
    </div>
  );
}

function EmptyWaterfallState({ ready, hasRun }: { ready: boolean; hasRun: boolean }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
      <Table2 className="mx-auto h-8 w-8 text-slate-400" />
      <p className="mt-3 font-medium text-slate-700">
        {hasRun ? 'No simulation results yet' : ready ? 'Run the solver to see the demand waterfall' : 'Waiting for complete BY file pack'}
      </p>
      <p className="mt-1 text-sm text-slate-500">
        {hasRun ? 'Run a simulation to populate the waterfall chart and bottleneck diagnostics.' : 'Upload all required entities to unlock simulation.'}
      </p>
    </div>
  );
}

function FlowStatus({ uploadedCount, isReady, hasRun, hasDeltas }: { uploadedCount: number; isReady: boolean; hasRun: boolean; hasDeltas: boolean }) {
  const steps = [
    { label: 'Load files', done: uploadedCount === 22 },
    { label: hasDeltas ? 'Tune scenario' : 'Baseline ready', done: isReady },
    { label: 'Run solver', done: hasRun },
    { label: 'Export patch', done: hasDeltas && hasRun },
  ];
  return <div className="mt-4 grid gap-2 sm:grid-cols-4">{steps.map((step) => <div key={step.label} className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${step.done ? 'border-green-200 bg-green-50 text-green-800' : 'border-slate-200 bg-slate-50 text-slate-500'}`}><CheckCircle2 className="h-4 w-4" />{step.label}</div>)}</div>;
}

function SolverExecutionBanner({ solverType, result, isReady }: { solverType: SolverType; result: RunSimulationResult | null; isReady: boolean }) {
  const selected = solverType === 'heuristic' ? 'Heuristic' : solverType === 'lpopt' ? 'LpOpt' : 'Compare Both';
  const executed = !result
    ? 'Not run yet'
    : isCompareResult(result)
      ? 'Heuristic + LpOpt comparison'
      : result.method === 'lp_highs'
        ? 'LpOpt'
        : 'Heuristic';
  const helper = solverType === 'compare_both'
    ? 'After you click Run Solver Comparison, the dashboard switches to the side-by-side comparative analysis.'
    : 'After you click Run Solver, the dashboard shows the selected solver output.';

  return <div className="mb-4 flex flex-col gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 sm:flex-row sm:items-center sm:justify-between"><div><span className="font-semibold">Selected solver:</span> {selected}<span className="mx-2 text-slate-300">|</span><span className="font-semibold">Executed:</span> {executed}</div><div className="text-slate-500">{isReady ? helper : 'Upload all 22 files to enable Run Solver.'}</div></div>;
}

function Panel({ title, icon: Icon, action, children }: { title: string; icon: typeof UploadCloud; action?: React.ReactNode; children: React.ReactNode }) {
  return <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-4 flex items-center justify-between gap-3"><h2 className="flex items-center gap-2 text-base font-semibold"><Icon className="h-5 w-5 text-blue-600" />{title}</h2>{action}</div>{children}</section>;
}

function RunSolverAction({ solverType, isReady, loading, missingCount, onRun }: { solverType: SolverType; isReady: boolean; loading: boolean; missingCount: number; onRun: () => void }) {
  const runLabel = solverType === 'compare_both' ? 'Run Solver Comparison' : 'Run Solver';

  return <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"><button onClick={onRun} disabled={!isReady || loading} title={isReady ? runLabel : `Upload ${missingCount} more files to run`} style={{ backgroundColor: '#000000', color: '#ffffff', opacity: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }} className="w-full rounded-md px-6 py-4 text-base font-bold uppercase tracking-wide shadow-sm hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-100"><span className="inline-flex items-center justify-center gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center">{loading ? <RefreshCw className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5" />}</span><span className="leading-none">{loading ? 'Running Solver...' : runLabel}</span></span></button>{!isReady && <p className="mt-2 text-center text-xs text-slate-500">Upload {missingCount} more files to enable solver execution.</p>}{isReady && <p className="mt-2 text-center text-xs text-slate-500">Overrides and mitigation levers are optional. With no changes selected, this runs the baseline data as-is.</p>}</section>;
}

function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  return <label onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); onFiles(Array.from(event.dataTransfer.files)); }} className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center hover:border-blue-400 hover:bg-blue-50"><input type="file" accept=".csv" multiple className="hidden" onChange={(event) => onFiles(Array.from(event.target.files || []))} /><UploadCloud className="mb-2 h-7 w-7 text-blue-600" /><span className="text-sm font-semibold">Drop or browse BY CSV pack</span><span className="mt-1 text-xs text-slate-500">All 22 if_snop files are required</span></label>;
}

function FileGrid({ files, onRemove }: { files: Record<string, File>; onRemove: (entity: string) => void }) {
  return <div className="mt-4 grid max-h-80 gap-2 overflow-auto sm:grid-cols-2 lg:grid-cols-3">{ALL_ENTITIES.map((entity) => { const file = files[entity]; return <div key={entity} className={`flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm ${file ? 'border-green-200 bg-green-50' : 'border-slate-200 bg-white'}`}><div className="min-w-0"><p className="font-medium">{ENTITY_LABELS[entity]}</p><p className="truncate text-xs text-slate-500">{file?.name || 'Required'}</p></div>{file ? <button onClick={() => onRemove(entity)} className="rounded p-1 text-slate-500 hover:bg-white hover:text-red-600" title="Remove file"><X className="h-4 w-4" /></button> : <FileCheck2 className="h-4 w-4 text-slate-300" />}</div>; })}</div>;
}

function ErrorList({ errors }: { errors: Record<string, string> }) {
  return <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{Object.entries(errors).map(([fileName, message]) => <div key={fileName}><span className="font-medium">{fileName}</span>: {message}</div>)}</div>;
}

function OverrideEditor({ draft, setDraft, activeType, onAdd }: { draft: RiskDraft; setDraft: (draft: RiskDraft) => void; activeType: typeof OVERRIDE_TYPES[keyof typeof OVERRIDE_TYPES]; onAdd: () => void }) {
  const value = Number(draft.value);
  const canAdd = Boolean(draft.key) && isValidOverrideValue(draft.type, value);
  return <div className="space-y-3"><label className="block text-xs font-semibold uppercase text-slate-500">Override Type<select value={draft.type} onChange={(event) => setDraft({ ...draft, type: event.target.value as RiskDraft['type'] })} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900">{Object.entries(OVERRIDE_TYPES).map(([type, meta]) => <option key={type} value={type}>{meta.label}</option>)}</select></label><label className="block text-xs font-semibold uppercase text-slate-500">{activeType.keyLabel}<input value={draft.key} onChange={(event) => setDraft({ ...draft, key: event.target.value })} placeholder={activeType.placeholder} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm font-normal text-slate-900" /></label><label className="block text-xs font-semibold uppercase text-slate-500">{activeType.valueLabel}<input type="number" min={0} max={draft.type === 'dfutoskufcst' ? undefined : 1} step="any" value={draft.value} onChange={(event) => setDraft({ ...draft, value: event.target.value })} placeholder={activeType.valueHint} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900" /></label><button onClick={onAdd} disabled={!canAdd} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"><Plus className="h-4 w-4" /> Add Override</button></div>;
}

function OverrideList({ overrides, onRemove }: { overrides: RiskOverrides; onRemove: (type: string, key: string) => void }) {
  const entries = Object.entries(overrides).flatMap(([type, values]) => Object.entries(values).map(([key, value]) => ({ type, key, value })));
  if (!entries.length) return null;
  return <div className="mt-4 space-y-2">{entries.map((entry) => <div key={`${entry.type}-${entry.key}`} className="flex items-center justify-between gap-2 rounded-md bg-slate-50 px-3 py-2 text-sm"><span className="min-w-0 truncate font-mono">{entry.key} {'->'} {formatOverrideValue(entry.type, entry.value)}</span><button onClick={() => onRemove(entry.type, entry.key)} className="rounded p-1 text-slate-500 hover:bg-white hover:text-red-600" title="Remove override"><X className="h-4 w-4" /></button></div>)}</div>;
}

function MitigationToolbar({ mitigations, setMitigations }: { mitigations: MitigationToggles; setMitigations: React.Dispatch<React.SetStateAction<MitigationToggles>> }) {
  return <Panel title="Mitigation Levers" icon={Wrench}><div className="grid gap-3 md:grid-cols-3"><ToggleButton label="15% Overtime" detail="Relieve saturated resources" active={mitigations.overtime} onClick={() => setMitigations((prev) => ({ ...prev, overtime: !prev.overtime }))} /><ToggleButton label="Expedite Lanes" detail="Add primary lane capacity" active={mitigations.expedite} onClick={() => setMitigations((prev) => ({ ...prev, expedite: !prev.expedite }))} /><ToggleButton label="Alternate BOMs" detail="Allow alternate routes" active={mitigations.altBom} onClick={() => setMitigations((prev) => ({ ...prev, altBom: !prev.altBom }))} /></div><p className="mt-3 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">Use the sticky action bar at the bottom of the screen to run the selected solver. Overrides and mitigation levers are optional.</p></Panel>;
}

function ToggleButton({ label, detail, active, onClick }: { label: string; detail: string; active: boolean; onClick: () => void }) {
  return <button onClick={onClick} className={`rounded-lg border p-3 text-left transition ${active ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}><span className="flex items-center justify-between gap-2"><span className="font-semibold">{label}</span><span className={`h-5 w-9 rounded-full p-0.5 ${active ? 'bg-blue-600' : 'bg-slate-300'}`}><span className={`block h-4 w-4 rounded-full bg-white transition ${active ? 'translate-x-4' : ''}`} /></span></span><span className="mt-1 block text-xs text-slate-500">{detail}</span></button>;
}

function DashboardBody({ result, waterfallData, diagnostics, impact, selectedDiagnostic, onSelectDiagnostic, onQuickMitigate }: { result: SolverResult; waterfallData: Array<Record<string, number | string>>; diagnostics: BottleneckDiagnostic[]; impact: Record<string, number>; selectedDiagnostic: BottleneckDiagnostic | null; onSelectDiagnostic: (row: BottleneckDiagnostic) => void; onQuickMitigate: () => void }) {
  return <div className="space-y-4"><DemandWaterfall data={waterfallData} impact={impact} /><BottleneckTable diagnostics={diagnostics} selected={selectedDiagnostic} onSelect={onSelectDiagnostic} onQuickMitigate={onQuickMitigate} /><ResultTables result={result} /></div>;
}

function DemandWaterfall({ data, impact }: { data: Array<Record<string, number | string>>; impact: Record<string, number> }) {
  return <div className="rounded-lg border border-slate-200 p-4"><div className="mb-4 grid gap-3 md:grid-cols-4"><Kpi label="Revenue Protected" value={formatCurrency(impact.protectedRevenue)} /><Kpi label="SLA / OTIF" value={`${impact.otif.toFixed(2)}%`} /><Kpi label="Mitigation Cost" value={formatCurrency(impact.mitigationCost)} /><Kpi label="ROI" value={`${impact.roi.toFixed(2)}x`} /></div><div className="h-64"><ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="scenario" /><YAxis /><Tooltip formatter={(value) => Number(value).toLocaleString()} /><Legend /><Bar dataKey="Met" stackId="a" fill="#16a34a" /><Bar dataKey="Late Met" stackId="a" fill="#f59e0b" /><Bar dataKey="Unmet" stackId="a" fill="#dc2626" /></BarChart></ResponsiveContainer></div></div>;
}

function BottleneckTable({ diagnostics, selected, onSelect, onQuickMitigate }: { diagnostics: BottleneckDiagnostic[]; selected: BottleneckDiagnostic | null; onSelect: (row: BottleneckDiagnostic) => void; onQuickMitigate: () => void }) {
  return <div className="rounded-lg border border-slate-200 p-4"><div className="mb-3 flex items-center justify-between gap-3"><h3 className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4 text-amber-500" /> Root-Cause Bottlenecks</h3><button onClick={onQuickMitigate} disabled={!selected} className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold hover:bg-slate-50 disabled:opacity-40"><Wrench className="h-4 w-4" /> Quick Mitigate</button></div>{diagnostics.length ? <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead className="bg-slate-50"><tr>{['Order', 'Item', 'Customer', 'Qty', 'Cause', 'Entity'].map((head) => <th key={head} className="px-3 py-2 text-left font-semibold text-slate-600">{head}</th>)}</tr></thead><tbody>{diagnostics.map((row) => <tr key={`${row.order_id}-${row.root_cause}`} onClick={() => onSelect(row)} className={`cursor-pointer border-t hover:bg-slate-50 ${selected?.order_id === row.order_id ? 'bg-blue-50' : ''}`}><td className="px-3 py-2 font-mono">{row.order_id}</td><td className="px-3 py-2">{row.item}</td><td className="px-3 py-2">{row.customer}</td><td className="px-3 py-2">{row.unmet_qty.toLocaleString()}</td><td className="px-3 py-2"><CauseTag cause={row.root_cause} /></td><td className="px-3 py-2">{row.bottleneck_entity}</td></tr>)}</tbody></table></div> : <p className="rounded-md bg-green-50 px-3 py-3 text-sm text-green-700">No late or unmet bottlenecks returned for this run.</p>}{selected && <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm"><p className="font-semibold">Recommendation</p><p className="mt-1 text-slate-600">{selected.suggested_mitigation}</p></div>}</div>;
}

function ResultTables({ result }: { result: SolverResult }) {
  return <div className="grid gap-4 lg:grid-cols-2"><MiniTable title="Shipments" rows={result.shipments || []} /><MiniTable title="Production" rows={result.production || []} /></div>;
}

function MiniTable({ title, rows }: { title: string; rows: Array<Record<string, unknown>> }) {
  const columns = rows[0] ? Object.keys(rows[0]).slice(0, 6) : [];
  return <div className="rounded-lg border border-slate-200 p-4"><h3 className="mb-3 font-semibold">{title}</h3>{rows.length ? <div className="max-h-72 overflow-auto"><table className="min-w-full text-xs"><thead className="bg-slate-50"><tr>{columns.map((column) => <th key={column} className="px-2 py-2 text-left font-semibold text-slate-600">{column}</th>)}</tr></thead><tbody>{rows.slice(0, 40).map((row, index) => <tr key={index} className="border-t">{columns.map((column) => <td key={column} className="px-2 py-2">{String(row[column] ?? '')}</td>)}</tr>)}</tbody></table></div> : <p className="text-sm text-slate-500">No rows returned.</p>}</div>;
}

function ExportModal({ deltas, impact, exporting, onClose, onExport }: { deltas: ScenarioDelta[]; impact: Record<string, number>; exporting: boolean; onClose: () => void; onExport: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 className="flex items-center gap-2 text-lg font-semibold"><PackageOpen className="h-5 w-5 text-blue-600" /> Export Center</h2><button onClick={onClose} className="rounded p-1 hover:bg-slate-100" title="Close"><X className="h-5 w-5" /></button></div><div className="grid gap-4 md:grid-cols-2"><div className="rounded-lg border border-slate-200 p-4"><h3 className="font-semibold">Diff Preview</h3><div className="mt-3 space-y-2">{deltas.map((delta, index) => <div key={index} className="rounded-md bg-slate-50 p-3 text-sm"><p className="font-mono">{delta.entity || delta.type}: {delta.key}</p><p className="text-slate-600">New value: {String(delta.value)}</p><p className="text-slate-500">{delta.justification}</p></div>)}{!deltas.length && <p className="text-sm text-slate-500">Baseline solve completed. No override or mitigation deltas were selected, so the export will contain the baseline run manifest.</p>}</div></div><div className="rounded-lg border border-slate-200 p-4"><h3 className="font-semibold">Changelog</h3><dl className="mt-3 space-y-2 text-sm"><div>Revenue protected: {formatCurrency(impact.protectedRevenue)}</div><div>Mitigation cost: {formatCurrency(impact.mitigationCost)}</div><div>Net ROI: {impact.roi.toFixed(2)}x</div><div>Tables touched: {new Set(deltas.map((delta) => delta.entity || delta.type)).size}</div></dl><button onClick={onExport} disabled={exporting} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-40"><Download className="h-4 w-4" /> {exporting ? 'Preparing...' : 'Download BY SCPO Patch Pack'}</button></div></div></div></div>;
}

function Kpi({ label, value }: { label: string; value: string }) { return <div className="rounded-md bg-slate-50 p-3"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>; }
function CauseTag({ cause }: { cause: string }) { const label = cause.includes('MATERIAL') ? 'Material' : cause.includes('CAPACITY') ? 'Capacity' : cause.includes('LEAD') ? 'Lead-Time' : cause.includes('SOURCING') ? 'Sourcing' : 'Other'; return <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{label}</span>; }
function AlertBox({ message }: { message: string }) { return <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertTriangle className="mt-0.5 h-4 w-4" /> <span>{message}</span></div>; }
function EmptyState({ ready }: { ready: boolean }) { return <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center"><Route className="mx-auto h-8 w-8 text-slate-400" /><p className="mt-3 font-medium text-slate-700">{ready ? 'Ready to simulate' : 'Waiting for complete BY file pack'}</p><p className="mt-1 text-sm text-slate-500">{ready ? 'Run the solver to populate fulfillment, bottleneck, and export panels.' : 'Upload all required entities to unlock simulation.'}</p></div>; }

function primaryResult(result: RunSimulationResult | null): SolverResult | null { return !result ? null : isCompareResult(result) ? result.lpopt_result : result; }
function buildWaterfallData(result: RunSimulationResult | null) { const current = primaryResult(result); if (!current) return [{ scenario: 'Baseline', Met: 0, 'Late Met': 0, Unmet: 0 }, { scenario: 'What-If', Met: 0, 'Late Met': 0, Unmet: 0 }]; const summary = current.summary || {}; const demand = numberValue(summary.total_demand_qty || summary.met_qty || current.shipments?.reduce((sum, row) => sum + numberValue(row.QUANTITY), 0)); return [{ scenario: 'Baseline', Met: demand, 'Late Met': 0, Unmet: 0 }, { scenario: 'What-If', Met: numberValue(summary.met_qty || demand), 'Late Met': numberValue(summary.late_qty), Unmet: numberValue(summary.unmet_qty) }]; }
function buildDiagnostics(result: SolverResult | null): BottleneckDiagnostic[] { if (!result) return []; if (result.diagnostics?.length) return result.diagnostics; return (result.pegging_records || []).filter((row) => row.status === 'UNMET' || row.status === 'LATE_MET').map((row) => ({ order_id: String(row.order_id || 'N/A'), item: String(row.item || 'N/A'), customer: String(row.customer || 'N/A'), unmet_qty: numberValue(row.allocated_qty), root_cause: row.status === 'LATE_MET' ? 'LEAD_TIME_CONSTRAINED' : 'SOURCING_CONSTRAINED', bottleneck_entity: String(row.bottleneck_reason || row.source_used || 'N/A'), suggested_mitigation: 'Use quick mitigation to add capacity, expedite sourcing, or enable alternate BOMs.' })); }
function buildImpact(result: RunSimulationResult | null, deltas: ScenarioDelta[]): Record<string, number> { const current = primaryResult(result); const summary = current?.summary || {}; const mitigationCost = deltas.reduce((sum, delta) => sum + numberValue(delta.financial_impact?.mitigation_cost), 0); const protectedRevenue = numberValue(summary.revenue_at_risk ? 0 : numberValue(summary.total_demand_qty) * 100); return { protectedRevenue, mitigationCost, roi: mitigationCost ? protectedRevenue / mitigationCost : 0, otif: numberValue(summary.met_pct) }; }
function buildScenarioDeltas(overrides: RiskOverrides): ScenarioDelta[] { return Object.entries(overrides).flatMap(([type, values]) => Object.entries(values).map(([key, value]) => ({ type, entity: type, key, value, justification: `${OVERRIDE_TYPES[type as keyof typeof OVERRIDE_TYPES]?.label || type} override`, financial_impact: { mitigation_cost: 0 } }))); }
function buildMitigationDeltas(mitigations: MitigationToggles, selected: BottleneckDiagnostic | null): ScenarioDelta[] { const key = selected?.order_id || 'AUTO'; const deltas: ScenarioDelta[] = []; if (mitigations.overtime) deltas.push({ type: 'res', entity: 'res', key, value: 0.15, column: 'CAPACITY', justification: 'Add 15% overtime to bottlenecked lines', financial_impact: { mitigation_cost: 8500 } }); if (mitigations.expedite) deltas.push({ type: 'sourcing', entity: 'sourcing', key, value: 0.1, justification: 'Expedite primary sourcing lanes', financial_impact: { mitigation_cost: 12000 } }); if (mitigations.altBom) deltas.push({ type: 'altbillofmaterials', entity: 'altbillofmaterials', key, value: 1, column: 'ENABLEOPT', justification: 'Enable alternate BOMs', financial_impact: { mitigation_cost: 5000 } }); return deltas; }
function extractEntityFromFilename(filename: string): string | null { const match = filename.match(/^if_snop_([a-z]+)-(?:\d{8}|\d{14}|\d{8}-\d{6})\.csv$/i); return match ? match[1].toLowerCase() : null; }
function withoutKey<T>(record: Record<string, T>, key: string): Record<string, T> { const next = { ...record }; delete next[key]; return next; }
function normalizeOverrideKey(key: string): string { return key.trim().replace(/\s+/g, '').toUpperCase(); }
function isValidOverrideValue(type: string, value: number): boolean { return Number.isFinite(value) && value >= 0 && (type === 'dfutoskufcst' || value <= 1); }
function formatOverrideValue(type: string, value: number): string { return type === 'dfutoskufcst' ? `${value}x` : `${Math.round(value * 100)}% reduction`; }
function extractBenchmarks(result: RunSimulationResult): { heuristic?: number; lpopt?: number } { if (isCompareResult(result)) return { heuristic: result.heuristic_result.summary?.solve_time_seconds, lpopt: result.lpopt_result.summary?.solve_time_seconds }; const seconds = result.summary?.solve_time_seconds || (result.solve_time_ms ? result.solve_time_ms / 1000 : undefined); return result.method === 'lp_highs' ? { lpopt: seconds } : { heuristic: seconds }; }
function formatCurrency(value: number): string { return value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }); }
