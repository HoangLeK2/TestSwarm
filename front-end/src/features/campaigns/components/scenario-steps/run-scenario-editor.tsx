'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { VariableEditor } from '@/components/variable-editor';
import type { FlowStep } from './types';
import { getStepIcon } from './types';
import { useTranslations } from 'next-intl';

export type RunScenarioCampaignOption = {
  id: string;
  name: string;
  steps?: any[];
};

/** Single merge — required so parent does not drop fields when two updates use the same stale `step` (e.g. template pick). */
export type RunScenarioFieldPatch = Partial<{
  scenario_id: string | undefined;
  scenario_name: string | undefined;
  variables: Record<string, any>;
}>;

type Props = {
  step: FlowStep;
  onPatch: (patch: RunScenarioFieldPatch) => void;
  /** Scenarios from the same campaign (optional). */
  campaignScenarios?: RunScenarioCampaignOption[];
  /** Wider controls + padding for step detail panel vs compact nested list. */
  layout?: 'compact' | 'panel';
};

const inputCls = 'border rounded px-1.5 py-0.5 bg-background text-[11px]';
const labelCls = 'shrink-0 text-[11px] text-muted-foreground';

export function RunScenarioFields({
  step,
  onPatch,
  campaignScenarios = [],
  layout = 'compact'
}: Props) {
  const t = useTranslations('campaignsFeature.scenarioStepsInline.runScenario');
  const { data: templates } = useScenarioTemplates();
  const [showPreview, setShowPreview] = useState(false);

  const allOptions: {
    id: string;
    name: string;
    source: string;
    steps?: any[];
    variables?: Record<string, any>;
  }[] = [
    ...campaignScenarios.map((s) => ({
      ...s,
      source: 'campaign',
      variables: {} as Record<string, any>
    })),
    ...(templates ?? []).map((t) => ({
      id: t.id,
      name: t.name,
      source: t.category,
      steps: t.steps,
      variables: t.variables
    }))
  ];

  const selected = allOptions.find(
    (o) => o.name === step.scenario_name || o.id === step.scenario_id
  );

  const handleSelect = (value: string) => {
    const option = allOptions.find((o) => `${o.source}:${o.name}` === value);
    if (!option) return;
    if (option.source === 'campaign') {
      onPatch({ scenario_id: option.id, scenario_name: undefined });
    } else {
      onPatch({ scenario_name: option.name, scenario_id: undefined });
    }
  };

  const panel = layout === 'panel';
  const selectCls = panel
    ? 'h-9 w-full min-w-0 flex-1 rounded-md border border-input bg-background px-2 py-1.5 text-sm shadow-sm sm:min-w-[200px]'
    : `${inputCls} flex-1 min-w-[160px]`;
  const manualCls = panel
    ? 'h-9 w-full min-w-0 rounded-md border border-input bg-background px-2 text-sm sm:max-w-[220px]'
    : `${inputCls} w-36`;

  return (
    <div className={panel ? 'space-y-4' : 'space-y-2'}>
      {/* Scenario picker */}
      <div
        className={
          panel
            ? 'flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center'
            : 'flex flex-wrap items-center gap-2'
        }
      >
        <span
          className={panel ? 'text-xs font-medium text-foreground' : labelCls}
        >
          {t('scenarioLabel')}
        </span>
        <select
          className={selectCls}
          value={selected ? `${selected.source}:${selected.name}` : ''}
          onChange={(e) => handleSelect(e.target.value)}
        >
          <option value=''>{t('selectScenario')}</option>
          {campaignScenarios.length > 0 && (
            <optgroup label={t('campaignScenarios')}>
              {campaignScenarios.map((s) => (
                <option key={s.id} value={`campaign:${s.name}`}>
                  {s.name}
                </option>
              ))}
            </optgroup>
          )}
          {(templates ?? []).length > 0 && (
            <optgroup label={t('sharedTemplates')}>
              {(templates ?? []).map((t) => (
                <option key={t.id} value={`${t.category}:${t.name}`}>
                  [{t.category}] {t.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <span className={panel ? 'text-xs text-muted-foreground' : labelCls}>
          {t('orNameLabel')}
        </span>
        <input
          className={manualCls}
          placeholder={t('scenarioNamePlaceholder')}
          value={step.scenario_name ?? ''}
          onChange={(e) => {
            onPatch({ scenario_name: e.target.value, scenario_id: undefined });
          }}
        />
      </div>

      {/* Variable overrides */}
      <div className='space-y-1.5'>
        <span
          className={
            panel
              ? 'text-xs font-medium text-muted-foreground'
              : `${labelCls} text-[10px]`
          }
        >
          {t('variableOverrides')}
        </span>
        <VariableEditor
          variables={step.variables ?? {}}
          onChange={(vars) => onPatch({ variables: vars })}
          showBuiltins={false}
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
            {showPreview ? (
              <ChevronDown size={10} />
            ) : (
              <ChevronRight size={10} />
            )}
            {t('preview', { count: selected.steps.length })}
          </button>
          {showPreview && (
            <div className='mt-1 max-h-40 overflow-y-auto rounded border bg-muted/30 p-2'>
              {selected.steps.map((s: any, i: number) => {
                const StepIcon = getStepIcon(s.type);
                return (
                  <div
                    key={i}
                    className='flex items-center gap-1 py-0.5 text-[10px] text-muted-foreground'
                  >
                    <span>
                      <StepIcon
                        size={12}
                        className='inline-block align-middle'
                      />
                    </span>
                    <span className='font-mono'>#{i + 1}</span>
                    <span className='font-medium'>{s.type}</span>
                    {s.package && (
                      <span className='truncate'>— {s.package}</span>
                    )}
                    {s.url && <span className='truncate'>— {s.url}</span>}
                    {s.value && <span className='truncate'>— {s.value}</span>}
                    {s.text && <span className='truncate'>— "{s.text}"</span>}
                    {s.seconds != null && <span>— {s.seconds}s</span>}
                    {s.count != null && <span>— ×{s.count}</span>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
