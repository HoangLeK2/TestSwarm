'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  arrayMove,
  useSortable,
} from '@dnd-kit/sortable';
import { restrictToVerticalAxis, restrictToParentElement } from '@dnd-kit/modifiers';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import { isControlFlow, type FlowStep } from '../scenario-steps/types';
import { StepCard } from './step-card';
import { BracketBlock } from './bracket-block';
import { InsertButton } from './insert-button';
import { StepDetailPanel } from './step-detail-panel';
import type { SelectorPickTarget } from './selector-pick';
import { selectorPickTargetEquals, isSelectorPickableStep } from './selector-pick';

// ── Sortable step wrapper ────────────────────────────────────────────────────

function SortableStepWrapper({
  id,
  children,
}: {
  id: string;
  children: (dragHandle: React.ReactNode, isDragging: boolean) => React.ReactNode;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition ?? undefined,
  };

  const dragHandle = (
    <button
      {...listeners}
      {...attributes}
      tabIndex={-1}
      title='Kéo để thay đổi thứ tự'
      className={[
        'flex shrink-0 cursor-grab items-center self-stretch px-1 text-muted-foreground/30',
        'hover:text-muted-foreground/70 active:cursor-grabbing',
        isDragging ? 'cursor-grabbing text-muted-foreground/70' : '',
      ].join(' ')}
    >
      <GripVertical size={11} />
    </button>
  );

  return (
    <div ref={setNodeRef} style={style} className={isDragging ? 'relative z-50 rounded shadow-lg' : ''}>
      {children(dragHandle, isDragging)}
    </div>
  );
}

// ── FlowEditor ───────────────────────────────────────────────────────────────

interface Props {
  steps: FlowStep[];
  onChange: (steps: FlowStep[]) => void;
  maxHeight?: string;
  /** Compact mode: no detail panel, used in narrow containers. */
  compact?: boolean;
  /** When set, user is assigning a selector from device/hierarchy to this step. */
  selectorPickTarget?: SelectorPickTarget | null;
  onSelectorPickTargetChange?: (target: SelectorPickTarget | null) => void;
  /** Run a single step on the device inline (without entering player mode). */
  onRunStep?: (step: FlowStep, index: number) => void;
  /** Per-step run state from the parent. */
  stepRunStates?: Record<number, 'idle' | 'running' | 'ok' | 'error'>;
}

export function FlowEditor({
  steps,
  onChange,
  maxHeight = '500px',
  compact = false,
  selectorPickTarget = null,
  onSelectorPickTargetChange,
  onRunStep,
  stepRunStates = {},
}: Props) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const selectedStep = selectedIndex != null ? steps[selectedIndex] : null;

  // Stable IDs for DnD — prefer _id, fall back to index-based
  const stepIds = useMemo(
    () => steps.map((s, i) => (s as any)._id ?? `step-idx-${i}`),
    [steps],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = stepIds.indexOf(active.id as string);
      const newIndex = stepIds.indexOf(over.id as string);
      if (oldIndex === -1 || newIndex === -1) return;
      const reordered = arrayMove(steps, oldIndex, newIndex);
      onChange(reordered);
      // Adjust selection
      if (selectedIndex === oldIndex) setSelectedIndex(newIndex);
      else if (selectedIndex != null) {
        if (oldIndex < selectedIndex && newIndex >= selectedIndex) setSelectedIndex(selectedIndex - 1);
        else if (oldIndex > selectedIndex && newIndex <= selectedIndex) setSelectedIndex(selectedIndex + 1);
      }
    },
    [stepIds, steps, onChange, selectedIndex],
  );

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
        if (selectorPickTarget?.rootIndex === index) {
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

  return (
    <>
      {/* Edit dialog */}
      <Dialog open={!compact && selectedIndex != null} onOpenChange={(open) => { if (!open) setSelectedIndex(null); }}>
        <DialogContent className='max-w-sm p-0 gap-0'>
          <DialogHeader className='sr-only'>
            <DialogTitle>Chỉnh sửa bước</DialogTitle>
          </DialogHeader>
          {selectedStep && selectedIndex != null && (
            <StepDetailPanel
              step={selectedStep}
              onChange={(s) => updateAt(selectedIndex, s)}
              onClose={() => setSelectedIndex(null)}
              onRequestPickSelector={
                onSelectorPickTargetChange
                  ? () => {
                      const idx = selectedIndex;
                      setSelectedIndex(null); // close dialog first
                      onSelectorPickTargetChange({ rootIndex: idx, path: [] });
                    }
                  : undefined
              }
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Flow list */}
      <div className='min-w-0'>
        <div className='overflow-y-auto' style={{ maxHeight }}>
          <InsertButton onInsert={(s) => insertAt(0, s)} />

          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
          >
            <SortableContext items={stepIds} strategy={verticalListSortingStrategy}>
              {steps.map((step, i) => (
                <div key={stepIds[i]}>
                  <SortableStepWrapper id={stepIds[i]!}>
                    {(dragHandle, isDragging) => (
                      <div className={`flex items-stretch ${isDragging ? 'opacity-60' : ''}`}>
                        {dragHandle}
                        <div className='min-w-0 flex-1'>
                          {isControlFlow(step.type) ? (
                            <BracketBlock
                              step={step}
                              stepIndex={i}
                              rootStepIndex={i}
                              pathFromRoot={[]}
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
                              onRunChild={onRunStep ? (s) => onRunStep(s, -1) : undefined}
                            />
                          ) : (
                            <StepCard
                              step={step}
                              index={i}
                              selected={!compact && selectedIndex === i}
                              onClick={() => !compact && setSelectedIndex(selectedIndex === i ? null : i)}
                              onRemove={() => removeAt(i)}
                              onRun={onRunStep ? () => onRunStep(step, i) : undefined}
                              runState={stepRunStates[i] ?? 'idle'}
                              isPickTarget={
                                selectorPickTarget != null &&
                                selectorPickTarget.rootIndex === i &&
                                (selectorPickTarget.path ?? []).length === 0
                              }
                              onTogglePickSelector={
                                onSelectorPickTargetChange && isSelectorPickableStep(step)
                                  ? () => togglePick({ rootIndex: i, path: [] })
                                  : undefined
                              }
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </SortableStepWrapper>
                  <InsertButton onInsert={(s) => insertAt(i + 1, s)} />
                </div>
              ))}
            </SortableContext>
          </DndContext>

          {steps.length === 0 && (
            <p className='py-6 text-center text-xs text-muted-foreground'>
              Nhấn <strong>+</strong> để thêm bước, hoặc ghi thao tác từ thiết bị.
            </p>
          )}
        </div>
      </div>
    </>
  );
}
