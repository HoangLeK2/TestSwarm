'use client';

import { useCallback, useState } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';
import {
  type FlowStep,
  isControlFlow,
  getStepIcon,
  createDefaultStep,
  ALL_STEP_TYPES
} from './types';
import {
  RepeatFields,
  RepeatUntilFields,
  IfElementFields,
  IfVariableFields,
  RandomPickFields
} from './control-flow-editors';
import { RunScenarioFields } from './run-scenario-editor';

// ─── Step field inline editor (for action steps) ─────────────────────────────

const inputCls = 'border rounded px-1.5 py-0.5 bg-background text-[11px]';

function ActionStepFields({
  step,
  onChange
}: {
  step: FlowStep;
  onChange: (field: string, value: any) => void;
}) {
  const t = useTranslations('campaignsFeature.scenarioStepsInline');
  switch (step.type) {
    case 'launch_app':
      return (
        <input className={`${inputCls} w-48`} placeholder={t('placeholder.package')} value={step.package ?? ''} onChange={(e) => onChange('package', e.target.value)} />
      );
    case 'open_url':
      return (
        <input className={`${inputCls} flex-1`} placeholder={t('placeholder.url')} value={step.url ?? ''} onChange={(e) => onChange('url', e.target.value)} />
      );
    case 'wait':
      return (
        <input type='number' min={0} step={0.5} className={`${inputCls} w-16`} value={step.seconds ?? 1} onChange={(e) => onChange('seconds', Number(e.target.value) || 0)} />
      );
    case 'tap_ratio':
      return (
        <div className='flex gap-1'>
          <input type='number' step={0.01} min={0} max={1} className={`${inputCls} w-16`} value={step.x ?? 0.5} onChange={(e) => onChange('x', parseFloat(e.target.value) || 0)} />
          <input type='number' step={0.01} min={0} max={1} className={`${inputCls} w-16`} value={step.y ?? 0.5} onChange={(e) => onChange('y', parseFloat(e.target.value) || 0)} />
        </div>
      );
    case 'tap_selector':
    case 'wait_element':
    case 'assert_element':
    case 'scroll_to':
      return (
        <div className='flex gap-1'>
          <select className={`${inputCls} w-24`} value={step.by ?? 'text'} onChange={(e) => onChange('by', e.target.value)}>
            {['text', 'resource-id', 'xpath', 'class name', 'description'].map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <input className={`${inputCls} flex-1 min-w-[80px]`} value={step.value ?? ''} onChange={(e) => onChange('value', e.target.value)} />
        </div>
      );
    case 'input_selector':
      return (
        <div className='flex flex-wrap gap-1'>
          <select className={`${inputCls} w-24`} value={step.by ?? 'resource-id'} onChange={(e) => onChange('by', e.target.value)}>
            {['text', 'resource-id', 'xpath', 'class name'].map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <input className={`${inputCls} w-28`} placeholder={t('placeholder.selector')} value={step.value ?? ''} onChange={(e) => onChange('value', e.target.value)} />
          <input className={`${inputCls} flex-1 min-w-[80px]`} placeholder={t('placeholder.textToInput')} value={step.text ?? ''} onChange={(e) => onChange('text', e.target.value)} />
        </div>
      );
    case 'input_text':
      return (
        <input className={`${inputCls} flex-1`} placeholder={t('placeholder.textToInput')} value={step.text ?? ''} onChange={(e) => onChange('text', e.target.value)} />
      );
    case 'set_variable':
      return (
        <div className='flex gap-1'>
          <input className={`${inputCls} w-24 font-mono`} placeholder={t('placeholder.varName')} value={step.name ?? ''} onChange={(e) => onChange('name', e.target.value)} />
          <span className='text-[11px] text-muted-foreground'>=</span>
          <input className={`${inputCls} flex-1`} placeholder={t('placeholder.valueOrBuiltin')} value={step.value ?? ''} onChange={(e) => onChange('value', e.target.value)} />
        </div>
      );
    case 'scroll_down':
      return (
        <div className='flex flex-1 min-w-0 items-center gap-1'>
          <input type='number' min={1} className={`${inputCls} w-14 shrink-0`} value={step.repeats ?? 1} onChange={(e) => onChange('repeats', Number(e.target.value) || 1)} />
          <span className='text-[10px] text-muted-foreground shrink-0'>x</span>
          <input
            className={`${inputCls} min-w-0 flex-1 font-mono`}
            placeholder='0.18'
            title={t('startXRatioTitle')}
            value={step.start_x_ratio != null ? String(step.start_x_ratio) : ''}
            onChange={(e) => {
              const v = e.target.value.trim();
              if (v === '') {
                onChange('start_x_ratio', undefined);
                return;
              }
              if (/^\$\{[^}]+\}$/.test(v)) {
                onChange('start_x_ratio', v);
                return;
              }
              const n = Number(v);
              onChange('start_x_ratio', Number.isFinite(n) ? n : v);
            }}
          />
        </div>
      );
    case 'key':
      return (
        <input className={`${inputCls} w-24`} placeholder={t('placeholder.key')} value={step.key ?? ''} onChange={(e) => onChange('key', e.target.value)} />
      );
    default:
      return null;
  }
}

// ─── Single step row ─────────────────────────────────────────────────────────

function StepRow({
  step,
  index,
  depth,
  prefix,
  onUpdate,
  onRemove,
  onMove,
  totalSiblings
}: {
  step: FlowStep;
  index: number;
  depth: number;
  prefix: string;
  onUpdate: (step: FlowStep) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  totalSiblings: number;
}) {
  const t = useTranslations('campaignsFeature.scenarioStepsInline');
  const [collapsed, setCollapsed] = useState(false);
  const controlFlow = isControlFlow(step.type);
  const Icon = getStepIcon(step.type);

  const updateField = useCallback(
    (field: string, value: any) => {
      const next = { ...step, [field]: value } as FlowStep;
      if (value === undefined) {
        delete (next as Record<string, unknown>)[field];
      }
      onUpdate(next);
    },
    [step, onUpdate]
  );

  const handleTypeChange = useCallback(
    (newType: string) => {
      onUpdate(createDefaultStep(newType));
    },
    [onUpdate]
  );

  // Sub-step lists for control flow
  const updateSubSteps = useCallback(
    (key: string, newSteps: FlowStep[]) => {
      onUpdate({ ...step, [key]: newSteps });
    },
    [step, onUpdate]
  );

  const addBranch = useCallback(() => {
    const branches = [...(step.branches ?? []), { weight: 1, steps: [] }];
    onUpdate({ ...step, branches });
  }, [step, onUpdate]);

  const removeBranch = useCallback(
    (bi: number) => {
      const branches = (step.branches ?? []).filter((_: any, i: number) => i !== bi);
      onUpdate({ ...step, branches });
    },
    [step, onUpdate]
  );

  const updateBranchWeight = useCallback(
    (bi: number, weight: number) => {
      const branches = [...(step.branches ?? [])];
      branches[bi] = { ...branches[bi], weight };
      onUpdate({ ...step, branches });
    },
    [step, onUpdate]
  );

  const updateBranchSteps = useCallback(
    (bi: number, newSteps: FlowStep[]) => {
      const branches = [...(step.branches ?? [])];
      branches[bi] = { ...branches[bi], steps: newSteps };
      onUpdate({ ...step, branches });
    },
    [step, onUpdate]
  );

  return (
    <div className={cn('rounded-md border', depth > 0 && 'border-dashed', controlFlow && 'border-primary/30 bg-primary/[0.02]')}>
      {/* Header row */}
      <div className='flex items-center gap-1 px-2 py-1.5'>
        {/* Reorder */}
        <div className='flex flex-col'>
          <button type='button' className='text-muted-foreground hover:text-foreground disabled:opacity-20' disabled={index === 0} onClick={() => onMove(-1)}>
            <ArrowUp size={10} />
          </button>
          <button type='button' className='text-muted-foreground hover:text-foreground disabled:opacity-20' disabled={index === totalSiblings - 1} onClick={() => onMove(1)}>
            <ArrowDown size={10} />
          </button>
        </div>

        {/* Collapse toggle for control flow */}
        {controlFlow && (
          <button type='button' className='text-muted-foreground hover:text-foreground' onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
        )}

        {/* Icon + number */}
        <span className='text-sm' title={step.type}>
          <Icon size={14} className='inline-block align-middle' />
        </span>
        <span className='text-[10px] font-mono text-muted-foreground'>{prefix}</span>

        {/* Type selector */}
        <select
          className='border rounded bg-background px-1 py-0.5 text-[11px] font-medium'
          value={step.type}
          onChange={(e) => handleTypeChange(e.target.value)}
        >
          <optgroup label={t('group.actions')}>
            {ALL_STEP_TYPES.filter((t) => t.group === 'action').map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </optgroup>
          <optgroup label={t('group.variables')}>
            {ALL_STEP_TYPES.filter((t) => t.group === 'variable').map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </optgroup>
          <optgroup label={t('group.controlFlow')}>
            {ALL_STEP_TYPES.filter((t) => t.group === 'control').map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </optgroup>
        </select>

        {/* Inline fields for action steps */}
        {!controlFlow && (
          <div className='flex flex-1 items-center gap-1 overflow-hidden'>
            <ActionStepFields step={step} onChange={updateField} />
          </div>
        )}

        {/* Control flow params */}
        {step.type === 'repeat' && <RepeatFields step={step} onChange={updateField} />}
        {step.type === 'repeat_until' && <RepeatUntilFields step={step} onChange={updateField} />}
        {step.type === 'if_element' && <IfElementFields step={step} onChange={updateField} />}
        {step.type === 'if_variable' && <IfVariableFields step={step} onChange={updateField} />}
        {step.type === 'random_pick' && <RandomPickFields step={step} onChange={updateField} />}

        {/* Delete - only show for non run_scenario (which has its own full section below) */}
        {step.type === 'run_scenario' && null}

        {/* Delete */}
        <button type='button' className='ml-auto shrink-0 p-0.5 text-destructive hover:bg-destructive/10 rounded' onClick={onRemove}>
          <Trash2 size={12} />
        </button>
      </div>

      {/* Nested content for control flow */}
      {controlFlow && !collapsed && (
        <div className='border-t px-2 pb-2'>
          {/* repeat / repeat_until → single `steps` list */}
          {(step.type === 'repeat' || step.type === 'repeat_until') && (
            <NestedStepList
              steps={step.steps ?? []}
              onChange={(s) => updateSubSteps('steps', s)}
              depth={depth + 1}
              parentPrefix={prefix}
              label={t('stepsLabel')}
            />
          )}

          {/* if_element / if_variable → then + else */}
          {(step.type === 'if_element' || step.type === 'if_variable') && (
            <>
              <NestedStepList
                steps={step.then ?? []}
                onChange={(s) => updateSubSteps('then', s)}
                depth={depth + 1}
                parentPrefix={prefix}
                label={t('thenLabel')}
              />
              <NestedStepList
                steps={step.else ?? []}
                onChange={(s) => updateSubSteps('else', s)}
                depth={depth + 1}
                parentPrefix={prefix}
                label={t('elseLabel')}
              />
            </>
          )}

          {/* random_pick → branches with weights */}
          {/* run_scenario → picker + variable overrides + preview */}
          {step.type === 'run_scenario' && (
            <div className='pt-2'>
              <RunScenarioFields step={step} onChange={updateField} />
            </div>
          )}

          {step.type === 'random_pick' && (
            <div className='space-y-1 pt-1'>
              {(step.branches ?? []).map((branch: any, bi: number) => (
                <div key={bi} className='rounded border border-dashed p-1'>
                  <div className='flex items-center gap-2 px-1 pb-1'>
                    <span className='text-[10px] font-medium text-muted-foreground'>
                      {t('branchLabel', { name: String.fromCharCode(65 + bi) })}
                    </span>
                    <span className='text-[10px] text-muted-foreground'>{t('weightLabel')}</span>
                    <input
                      type='number'
                      min={1}
                      className='w-12 border rounded px-1 py-0.5 bg-background text-[11px]'
                      value={branch.weight ?? 1}
                      onChange={(e) => updateBranchWeight(bi, Number(e.target.value) || 1)}
                    />
                    <button
                      type='button'
                      className='ml-auto p-0.5 text-destructive hover:bg-destructive/10 rounded'
                      onClick={() => removeBranch(bi)}
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                  <NestedStepList
                    steps={branch.steps ?? []}
                    onChange={(s) => updateBranchSteps(bi, s)}
                    depth={depth + 1}
                    parentPrefix={`${prefix}${String.fromCharCode(65 + bi)}.`}
                    label=''
                  />
                </div>
              ))}
              <Button type='button' size='sm' variant='ghost' className='h-6 text-[10px]' onClick={addBranch}>
                <Plus size={10} className='mr-1' />
                {t('addBranch')}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Recursive step list ─────────────────────────────────────────────────────

export function NestedStepList({
  steps,
  onChange,
  depth = 0,
  parentPrefix = '',
  label
}: {
  steps: FlowStep[];
  onChange: (steps: FlowStep[]) => void;
  depth?: number;
  parentPrefix?: string;
  label?: string;
}) {
  const t = useTranslations('campaignsFeature.scenarioStepsInline');
  const addStep = useCallback(
    (type = 'wait') => {
      onChange([...steps, createDefaultStep(type)]);
    },
    [steps, onChange]
  );

  const updateStep = useCallback(
    (index: number, newStep: FlowStep) => {
      const next = [...steps];
      next[index] = newStep;
      onChange(next);
    },
    [steps, onChange]
  );

  const removeStep = useCallback(
    (index: number) => {
      onChange(steps.filter((_, i) => i !== index));
    },
    [steps, onChange]
  );

  const moveStep = useCallback(
    (index: number, dir: -1 | 1) => {
      const to = index + dir;
      if (to < 0 || to >= steps.length) return;
      const next = [...steps];
      [next[index], next[to]] = [next[to], next[index]];
      onChange(next);
    },
    [steps, onChange]
  );

  return (
    <div className={cn('space-y-1', depth > 0 && 'pl-3 pt-1')}>
      {label && (
        <p className='text-[10px] font-semibold uppercase tracking-wider text-muted-foreground'>
          {label}:
        </p>
      )}
      {steps.map((step, i) => (
        <StepRow
          key={i}
          step={step}
          index={i}
          depth={depth}
          prefix={`${parentPrefix}${i + 1}.`}
          onUpdate={(s) => updateStep(i, s)}
          onRemove={() => removeStep(i)}
          onMove={(dir) => moveStep(i, dir)}
          totalSiblings={steps.length}
        />
      ))}
      <Button type='button' size='sm' variant='ghost' className='h-6 text-[10px] text-muted-foreground' onClick={() => addStep()}>
        <Plus size={10} className='mr-1' />
        {depth === 0 ? t('addStep') : t('add')}
      </Button>
    </div>
  );
}
