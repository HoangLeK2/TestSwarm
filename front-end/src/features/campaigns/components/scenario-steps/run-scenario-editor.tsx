'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { VariableEditor } from '@/components/variable-editor';
import type { FlowStep } from './types';
import { getStepIcon } from './types';

type Props = {
  step: FlowStep;
  onChange: (field: string, value: any) => void;
  /** Scenarios from the same campaign (optional). */
  campaignScenarios?: { id: string; name: string; steps?: any[] }[];
};

const inputCls = 'border rounded px-1.5 py-0.5 bg-background text-[11px]';
const labelCls = 'shrink-0 text-[11px] text-muted-foreground';

export function RunScenarioFields({ step, onChange, campaignScenarios = [] }: Props) {
  const { data: templates } = useScenarioTemplates();
  const [showPreview, setShowPreview] = useState(false);

  const allOptions: { id: string; name: string; source: string; steps?: any[]; variables?: Record<string, any> }[] = [
    ...campaignScenarios.map((s) => ({ ...s, source: 'campaign', variables: {} as Record<string, any> })),
    ...(templates ?? []).map((t) => ({ id: t.id, name: t.name, source: t.category, steps: t.steps, variables: t.variables }))
  ];

  const selected = allOptions.find(
    (o) => o.name === step.scenario_name || o.id === step.scenario_id
  );

  const handleSelect = (value: string) => {
    const option = allOptions.find((o) => `${o.source}:${o.name}` === value);
    if (option) {
      if (option.source === 'campaign') {
        onChange('scenario_id', option.id);
        onChange('scenario_name', undefined);
      } else {
        onChange('scenario_name', option.name);
        onChange('scenario_id', undefined);
      }
    }
  };

  return (
    <div className='space-y-2'>
      {/* Scenario picker */}
      <div className='flex flex-wrap items-center gap-2'>
        <span className={labelCls}>scenario:</span>
        <select
          className={`${inputCls} flex-1 min-w-[160px]`}
          value={selected ? `${selected.source}:${selected.name}` : ''}
          onChange={(e) => handleSelect(e.target.value)}
        >
          <option value=''>-- select scenario --</option>
          {campaignScenarios.length > 0 && (
            <optgroup label='Campaign Scenarios'>
              {campaignScenarios.map((s) => (
                <option key={s.id} value={`campaign:${s.name}`}>
                  {s.name}
                </option>
              ))}
            </optgroup>
          )}
          {(templates ?? []).length > 0 && (
            <optgroup label='Shared Templates'>
              {(templates ?? []).map((t) => (
                <option key={t.id} value={`${t.category}:${t.name}`}>
                  [{t.category}] {t.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <span className={labelCls}>or name:</span>
        <input
          className={`${inputCls} w-36`}
          placeholder='scenario_name'
          value={step.scenario_name ?? ''}
          onChange={(e) => {
            onChange('scenario_name', e.target.value);
            onChange('scenario_id', undefined);
          }}
        />
      </div>

      {/* Variable overrides */}
      <div className='space-y-1'>
        <span className={`${labelCls} text-[10px]`}>
          variable overrides (optional):
        </span>
        <VariableEditor
          variables={step.variables ?? {}}
          onChange={(vars) => onChange('variables', vars)}
          placeholder={{ key: 'VAR_NAME', value: 'override value' }}
        />
      </div>

      {/* Preview sub-scenario steps */}
      {selected?.steps && selected.steps.length > 0 && (
        <div>
          <button
            type='button'
            className='flex items-center gap-1 text-[10px] text-primary hover:underline'
            onClick={() => setShowPreview((v) => !v)}
          >
            {showPreview ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            Preview ({selected.steps.length} steps)
          </button>
          {showPreview && (
            <div className='mt-1 max-h-40 overflow-y-auto rounded border bg-muted/30 p-2'>
              {selected.steps.map((s: any, i: number) => (
                <div key={i} className='flex items-center gap-1 text-[10px] text-muted-foreground py-0.5'>
                  <span>{getStepIcon(s.type)}</span>
                  <span className='font-mono'>#{i + 1}</span>
                  <span className='font-medium'>{s.type}</span>
                  {s.package && <span className='truncate'>— {s.package}</span>}
                  {s.url && <span className='truncate'>— {s.url}</span>}
                  {s.value && <span className='truncate'>— {s.value}</span>}
                  {s.text && <span className='truncate'>— "{s.text}"</span>}
                  {s.seconds != null && <span>— {s.seconds}s</span>}
                  {s.count != null && <span>— ×{s.count}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
