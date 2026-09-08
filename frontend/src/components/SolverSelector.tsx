'use client';

import { BadgeCheck, GitCompareArrows, Zap } from 'lucide-react';
import type { SolverType } from '@/src/services/simulationApi';

interface SolverSelectorProps {
  solverType: SolverType;
  onChange: (solverType: SolverType) => void;
  heuristicSeconds?: number;
  lpoptSeconds?: number;
  disabled?: boolean;
}

const SOLVERS: Array<{ value: SolverType; label: string; description: string; tooltip: string; icon: typeof Zap }> = [
  {
    value: 'heuristic',
    label: 'Heuristic',
    description: 'Priority pegging',
    tooltip: 'Priority-driven backward/forward pass. Sub-second solve time for interactive What-Ifs.',
    icon: Zap,
  },
  {
    value: 'lpopt',
    label: 'LpOpt',
    description: 'Global LP solve',
    tooltip: 'Simultaneous linear programming via HiGHS. Minimizes global landed cost across multi-echelon lanes.',
    icon: BadgeCheck,
  },
  {
    value: 'compare_both',
    label: 'Compare',
    description: 'Gap analysis',
    tooltip: 'Runs both engines in parallel and renders side-by-side gap analysis.',
    icon: GitCompareArrows,
  },
];

export default function SolverSelector({ solverType, onChange, heuristicSeconds, lpoptSeconds, disabled }: SolverSelectorProps) {
  const benchmark = formatBenchmark(heuristicSeconds, lpoptSeconds);

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="inline-flex flex-col rounded-md border border-slate-200 bg-slate-50 p-1 sm:flex-row">
        {SOLVERS.map((solver) => {
          const active = solverType === solver.value;
          const Icon = solver.icon;
          return (
            <button
              key={solver.value}
              type="button"
              title={solver.tooltip}
              disabled={disabled}
              onClick={() => onChange(solver.value)}
              className={`rounded px-3 py-2 text-left text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                active
                  ? 'bg-white text-blue-700 shadow-sm'
                  : 'text-slate-600 hover:bg-white/70'
              }`}
            >
              <span className="flex items-center gap-2 whitespace-nowrap"><Icon className="h-4 w-4" />{solver.label}</span>
              <span className={`block text-xs font-normal ${active ? 'text-blue-500' : 'text-slate-500'}`}>
                {solver.description}
              </span>
            </button>
          );
        })}
      </div>

      <div className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm font-medium text-slate-600">
        {benchmark}
      </div>
    </div>
  );
}

function formatBenchmark(heuristicSeconds?: number, lpoptSeconds?: number): string {
  const heuristic = typeof heuristicSeconds === 'number' ? `${heuristicSeconds.toFixed(2)}s` : '--';
  const lpopt = typeof lpoptSeconds === 'number' ? `${lpoptSeconds.toFixed(2)}s` : '--';
  return `Heuristic ${heuristic} vs LpOpt ${lpopt}`;
}