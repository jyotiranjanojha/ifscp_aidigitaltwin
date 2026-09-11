'use client';

import { DollarSign, Target } from 'lucide-react';

export type ObjectiveMode = 'MAX_DEMAND_FULFILLMENT' | 'MIN_COST';

interface ObjectiveModeSelectorProps {
  objectiveMode: ObjectiveMode;
  onChange: (mode: ObjectiveMode) => void;
  disabled?: boolean;
}

const MODES: Array<{
  value: ObjectiveMode;
  label: string;
  icon: typeof Target;
  tooltip: string;
}> = [
  {
    value: 'MAX_DEMAND_FULFILLMENT',
    label: 'Maximize Demand (SLA)',
    icon: Target,
    tooltip: 'Prioritizes 100% Customer Fill Rate and on-time delivery above all costs. Uses overtime, alternate BOMs, and expedited freight if necessary. Automatically uses the LP solver.',
  },
  {
    value: 'MIN_COST',
    label: 'Minimize Cost (Budget)',
    icon: DollarSign,
    tooltip: 'Minimizes total supply chain cost (production, transportation, holding) while fulfilling demand within standard operating limits.',
  },
];

export default function ObjectiveModeSelector({ objectiveMode, onChange, disabled }: ObjectiveModeSelectorProps) {
  const isSLA = objectiveMode === 'MAX_DEMAND_FULFILLMENT';
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
      <div className="inline-flex flex-col rounded-md border border-slate-200 bg-slate-50 p-1 sm:flex-row">
        {MODES.map((mode) => {
          const active = objectiveMode === mode.value;
          const Icon = mode.icon;
          return (
            <button
              key={mode.value}
              type="button"
              title={mode.tooltip}
              disabled={disabled}
              onClick={() => onChange(mode.value)}
              className={`rounded px-3 py-2 text-left text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                active
                  ? mode.value === 'MAX_DEMAND_FULFILLMENT'
                    ? 'bg-emerald-600 text-white shadow-sm'
                    : 'bg-amber-600 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-white/70'
              }`}
            >
              <span className="flex items-center gap-2 whitespace-nowrap">
                <Icon className="h-4 w-4" />
                {mode.label}
              </span>
            </button>
          );
        })}
      </div>
      {isSLA && (
        <span className="text-xs font-medium text-emerald-600">LP solver auto-selected</span>
      )}
    </div>
  );
}
