'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Crosshair, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { type FlowStep } from '../scenario-steps/types';
import { BRACKET_COLORS, getStepTypeName, getStepSummary } from './constants';
import { StepIcon } from './step-icon';
import { StepCard } from './step-card';
import { InsertButton } from './insert-button';
import {
  RepeatFields,
  RepeatUntilFields,
  IfElementFields,
  IfVariableFields,
} from '../scenario-steps/control-flow-editors';
import type { SelectorPickTarget } from './selector-pick';
import { selectorPickTargetEquals } from './selector-pick';

interface Props {
  step: FlowStep;
  stepIndex: number;
  selected: boolean;
  selectedChild: number | null;
  onSelectSelf: () => void;
  onSelectChild: (flatIndex: number) => void;
  onUpdate: (step: FlowStep) => void;
  onRemove: () => void;
  onRemoveChild: (key: string, childIndex: number) => void;
  onInsertChild: (key: string, insertAt: number, newStep: FlowStep) => void;
  /** Compact mode: show inline parameter editor when selected instead of detail panel. */
  compact?: boolean;
  selectorPickTarget?: SelectorPickTarget | null;
  onTogglePickSelector?: (path: SelectorPickTarget) => void;
}

function SectionLabel({ label, color }: { label: string; color: string }) {
  return (
    <div className={cn('py-0.5 text-[9px] font-bold uppercase tracking-widest', color)}>
      {label}
    </div>
  );
}

function ChildStepList({
  steps,
  listKey,
  selectedChild,
  startIndex,
  onSelectChild,
  onRemoveChild,
  onInsertChild,
  parentStepIndex,
  selectorPickTarget,
  onTogglePickSelector,
}: {
  steps: FlowStep[];
  listKey: string;
  selectedChild: number | null;
  startIndex: number;
  onSelectChild: (flatIndex: number) => void;
  onRemoveChild: (key: string, childIndex: number) => void;
  onInsertChild: (key: string, insertAt: number, newStep: FlowStep) => void;
  parentStepIndex: number;
  selectorPickTarget?: SelectorPickTarget | null;
  onTogglePickSelector?: (path: SelectorPickTarget) => void;
}) {
  return (
    <div className='space-y-0'>
      <InsertButton onInsert={(s) => onInsertChild(listKey, 0, s)} />
      {steps.map((child, ci) => {
        const path: SelectorPickTarget = {
          kind: 'child',
          parentIndex: parentStepIndex,
          listKey,
          childIndex: ci,
        };
        return (
          <div key={ci}>
            <StepCard
              step={child}
              index={startIndex + ci}
              selected={selectedChild === startIndex + ci}
              onClick={() => onSelectChild(startIndex + ci)}
              onRemove={() => onRemoveChild(listKey, ci)}
              stepPath={path}
              selectorPickTarget={selectorPickTarget}
              onTogglePickSelector={onTogglePickSelector}
            />
            <InsertButton onInsert={(s) => onInsertChild(listKey, ci + 1, s)} />
          </div>
        );
      })}
      {steps.length === 0 && (
        <p className='py-1 text-center text-[10px] text-muted-foreground'>Trống</p>
      )}
    </div>
  );
}

export function BracketBlock({
  step, stepIndex, selected, selectedChild,
  onSelectSelf, onSelectChild, onUpdate, onRemove, onRemoveChild, onInsertChild,
  compact = false,
  selectorPickTarget,
  onTogglePickSelector,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const colors = BRACKET_COLORS[step.type] ?? BRACKET_COLORS.repeat;
  const typeName = getStepTypeName(step.type);
  const summary = getStepSummary(step);
  const rootPickPath: SelectorPickTarget = { kind: 'root', index: stepIndex };
  const pickingCondition =
    step.type === 'if_element' &&
    selectorPickTarget &&
    selectorPickTargetEquals(selectorPickTarget, rootPickPath);

  return (
    <div
      className={cn(
        'rounded-md border-2 overflow-hidden',
        colors.border,
        selected && 'ring-2 ring-primary/40',
        pickingCondition && 'ring-2 ring-amber-500/80 shadow-[0_0_0_1px_rgba(245,158,11,0.35)]',
      )}
    >
      {/* Header */}
      <div
        className={cn('flex cursor-pointer items-center gap-1.5 px-2 py-1.5', colors.bg)}
        onClick={onSelectSelf}
      >
        <button type='button' className='shrink-0' onClick={(e) => { e.stopPropagation(); setCollapsed((v) => !v); }}>
          {collapsed ? <ChevronRight size={11} strokeWidth={2} /> : <ChevronDown size={11} strokeWidth={2} />}
        </button>
        <StepIcon type={step.type} size={12} />
        <span className={cn('text-[11px] font-bold', colors.label)}>{typeName}</span>
        <span className='min-w-0 flex-1 truncate text-[10px] text-muted-foreground'>{summary}</span>
        {step.type === 'if_element' && onTogglePickSelector && (
          <button
            type='button'
            className={cn(
              'shrink-0 rounded p-0.5 hover:bg-amber-500/15',
              pickingCondition && 'bg-amber-500/25 text-amber-800 dark:text-amber-200',
            )}
            title='Chọn phần tử điều kiện trên màn hình'
            aria-label='Chọn selector điều kiện if_element trên màn hình'
            onClick={(e) => {
              e.stopPropagation();
              onTogglePickSelector(rootPickPath);
            }}
          >
            <Crosshair size={12} strokeWidth={2} />
          </button>
        )}
        <button
          type='button'
          className='shrink-0 rounded p-0.5 hover:bg-destructive/10 hover:text-destructive'
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
        >
          <Trash2 size={10} strokeWidth={2} />
        </button>
      </div>

      {/* Inline parameter editor — shown in compact mode when block is selected */}
      {compact && selected && (
        <div className='border-t px-2 py-1.5 bg-accent/30'>
          {step.type === 'repeat' && (
            <RepeatFields step={step} onChange={(f, v) => onUpdate({ ...step, [f]: v })} />
          )}
          {step.type === 'repeat_until' && (
            <RepeatUntilFields step={step} onChange={(f, v) => onUpdate({ ...step, [f]: v })} />
          )}
          {step.type === 'if_element' && (
            <IfElementFields step={step} onChange={(f, v) => onUpdate({ ...step, [f]: v })} />
          )}
          {step.type === 'if_variable' && (
            <IfVariableFields step={step} onChange={(f, v) => onUpdate({ ...step, [f]: v })} />
          )}
        </div>
      )}

      {/* Body */}
      {!collapsed && (
        <div className='px-2 pb-1'>
          {(step.type === 'repeat' || step.type === 'repeat_until') && (
            <ChildStepList
              steps={step.steps ?? []} listKey='steps' selectedChild={selectedChild}
              startIndex={0} onSelectChild={onSelectChild}
              onRemoveChild={onRemoveChild} onInsertChild={onInsertChild}
              parentStepIndex={stepIndex}
              selectorPickTarget={selectorPickTarget}
              onTogglePickSelector={onTogglePickSelector}
            />
          )}

          {(step.type === 'if_element' || step.type === 'if_variable') && (() => {
            const thenSteps = step.then ?? [];
            const elseSteps = step.else ?? [];
            return (
              <>
                <SectionLabel label='Thì →' color={colors.label} />
                <ChildStepList
                  steps={thenSteps} listKey='then' selectedChild={selectedChild}
                  startIndex={0} onSelectChild={onSelectChild}
                  onRemoveChild={onRemoveChild} onInsertChild={onInsertChild}
                  parentStepIndex={stepIndex}
                  selectorPickTarget={selectorPickTarget}
                  onTogglePickSelector={onTogglePickSelector}
                />
                <SectionLabel label='Ngược lại →' color={colors.label} />
                <ChildStepList
                  steps={elseSteps} listKey='else' selectedChild={selectedChild}
                  startIndex={thenSteps.length} onSelectChild={onSelectChild}
                  onRemoveChild={onRemoveChild} onInsertChild={onInsertChild}
                  parentStepIndex={stepIndex}
                  selectorPickTarget={selectorPickTarget}
                  onTogglePickSelector={onTogglePickSelector}
                />
              </>
            );
          })()}

          {step.type === 'random_pick' && (
            <div className='space-y-1 pt-0.5'>
              {(step.branches ?? []).map((branch: any, bi: number) => (
                <div key={bi} className='rounded border border-dashed p-1.5'>
                  <span className={cn('text-[9px] font-bold', colors.label)}>
                    Nhánh {String.fromCharCode(65 + bi)} (w={branch.weight ?? 1})
                  </span>
                  <ChildStepList
                    steps={branch.steps ?? []} listKey={`branches.${bi}.steps`}
                    selectedChild={selectedChild} startIndex={0}
                    onSelectChild={onSelectChild} onRemoveChild={onRemoveChild}
                    onInsertChild={onInsertChild}
                    parentStepIndex={stepIndex}
                    selectorPickTarget={selectorPickTarget}
                    onTogglePickSelector={onTogglePickSelector}
                  />
                </div>
              ))}
            </div>
          )}

          {step.type === 'run_scenario' && (
            <p className='py-1 text-[10px] text-muted-foreground'>
              Gọi: <span className='font-mono'>{step.scenario_name || step.scenario_id || '(chưa chọn)'}</span>
            </p>
          )}
        </div>
      )}

      {/* End bar */}
      {!collapsed && (
        <div className={cn('border-t px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest', colors.bg, colors.label)}>
          KẾT THÚC {typeName}
        </div>
      )}
    </div>
  );
}
