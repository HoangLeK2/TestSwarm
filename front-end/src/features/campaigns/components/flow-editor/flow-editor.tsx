'use client';

import { useCallback, useEffect, useState } from 'react';
import { isControlFlow, type FlowStep } from '../scenario-steps/types';
import { StepCard } from './step-card';
import { BracketBlock } from './bracket-block';
import { InsertButton } from './insert-button';
import { StepDetailPanel } from './step-detail-panel';
import type { SelectorPickTarget } from './selector-pick';
import { selectorPickTargetEquals } from './selector-pick';

interface Props {
  steps: FlowStep[];
  onChange: (steps: FlowStep[]) => void;
  maxHeight?: string;
  /** Compact mode: no detail panel, used in narrow containers. */
  compact?: boolean;
  /** When set, user is assigning a selector from device/hierarchy to this step. */
  selectorPickTarget?: SelectorPickTarget | null;
  onSelectorPickTargetChange?: (target: SelectorPickTarget | null) => void;
}

export function FlowEditor({
  steps,
  onChange,
  maxHeight = '500px',
  compact = false,
  selectorPickTarget = null,
  onSelectorPickTargetChange,
}: Props) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const selectedStep = selectedIndex != null ? steps[selectedIndex] : null;

  const togglePick = useCallback(
    (path: SelectorPickTarget) => {
      if (!onSelectorPickTargetChange) return;
      onSelectorPickTargetChange(
        selectorPickTargetEquals(selectorPickTarget, path) ? null : path,
      );
    },
    [onSelectorPickTargetChange, selectorPickTarget],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectorPickTarget && onSelectorPickTargetChange) {
        onSelectorPickTargetChange(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectorPickTarget, onSelectorPickTargetChange]);

  const insertAt = useCallback(
    (index: number, newStep: FlowStep) => {
      const next = [...steps];
      next.splice(index, 0, newStep);
      onChange(next);
    },
    [steps, onChange],
  );

  const removeAt = useCallback(
    (index: number) => {
      onChange(steps.filter((_, i) => i !== index));
      if (selectedIndex === index) setSelectedIndex(null);
      if (onSelectorPickTargetChange) {
        if (selectorPickTarget?.kind === 'root' && selectorPickTarget.index === index) {
          onSelectorPickTargetChange(null);
        }
      }
    },
    [steps, onChange, selectedIndex, selectorPickTarget, onSelectorPickTargetChange],
  );

  const updateAt = useCallback(
    (index: number, newStep: FlowStep) => {
      const next = [...steps];
      next[index] = newStep;
      onChange(next);
    },
    [steps, onChange],
  );

  const removeChild = useCallback(
    (parentIndex: number, key: string, childIndex: number) => {
      const parent = steps[parentIndex];
      if (!parent) return;
      const next = { ...parent };
      if (key.startsWith('branches.')) {
        const bi = parseInt(key.split('.')[1] ?? '0');
        const branches = [...(next.branches ?? [])];
        branches[bi] = {
          ...branches[bi],
          steps: branches[bi].steps.filter((_: unknown, i: number) => i !== childIndex),
        };
        next.branches = branches;
      } else {
        next[key] = (next[key] ?? []).filter((_: unknown, i: number) => i !== childIndex);
      }
      updateAt(parentIndex, next);
    },
    [steps, updateAt],
  );

  const insertChild = useCallback(
    (parentIndex: number, key: string, at: number, newStep: FlowStep) => {
      const parent = steps[parentIndex];
      if (!parent) return;
      const next = { ...parent };
      if (key.startsWith('branches.')) {
        const bi = parseInt(key.split('.')[1] ?? '0');
        const branches = [...(next.branches ?? [])];
        const bSteps = [...(branches[bi].steps ?? [])];
        bSteps.splice(at, 0, newStep);
        branches[bi] = { ...branches[bi], steps: bSteps };
        next.branches = branches;
      } else {
        const arr = [...(next[key] ?? [])];
        arr.splice(at, 0, newStep);
        next[key] = arr;
      }
      updateAt(parentIndex, next);
    },
    [steps, updateAt],
  );

  const showPanel = !compact && selectedStep && selectedIndex != null;

  return (
    <div className={showPanel ? 'flex gap-0' : ''}>
      {/* Flow list */}
      <div className='min-w-0 flex-1'>
        <div className='overflow-y-auto' style={{ maxHeight }}>
          <InsertButton onInsert={(s) => insertAt(0, s)} />

          {steps.map((step, i) => (
            <div key={i}>
              {isControlFlow(step.type) ? (
                <BracketBlock
                  step={step}
                  stepIndex={i}
                  selected={selectedIndex === i}
                  selectedChild={null}
                  onSelectSelf={() => setSelectedIndex(selectedIndex === i ? null : i)}
                  onSelectChild={() => {}}
                  onUpdate={(s) => updateAt(i, s)}
                  onRemove={() => removeAt(i)}
                  onRemoveChild={(key, ci) => removeChild(i, key, ci)}
                  onInsertChild={(key, at, s) => insertChild(i, key, at, s)}
                  compact={compact}
                  selectorPickTarget={selectorPickTarget}
                  onTogglePickSelector={onSelectorPickTargetChange ? togglePick : undefined}
                />
              ) : (
                <StepCard
                  step={step}
                  index={i}
                  selected={!compact && selectedIndex === i}
                  onClick={() => !compact && setSelectedIndex(selectedIndex === i ? null : i)}
                  onRemove={() => removeAt(i)}
                  stepPath={{ kind: 'root', index: i }}
                  selectorPickTarget={selectorPickTarget}
                  onTogglePickSelector={onSelectorPickTargetChange ? togglePick : undefined}
                />
              )}
              <InsertButton onInsert={(s) => insertAt(i + 1, s)} />
            </div>
          ))}

          {steps.length === 0 && (
            <p className='py-6 text-center text-xs text-muted-foreground'>
              Nhấn <strong>+</strong> để thêm bước, hoặc ghi thao tác từ thiết bị.
            </p>
          )}
        </div>
      </div>

      {/* Detail panel — only in non-compact mode */}
      {showPanel && (
        <div className='w-72 shrink-0' style={{ maxHeight }}>
          <div className='h-full overflow-y-auto'>
            <StepDetailPanel
              step={selectedStep!}
              onChange={(s) => updateAt(selectedIndex!, s)}
              onClose={() => setSelectedIndex(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
