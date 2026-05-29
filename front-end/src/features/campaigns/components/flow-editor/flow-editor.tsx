'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy
} from '@dnd-kit/sortable';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { isContainerType, type FlowStep } from '../scenario-steps/types';
import type { RunScenarioCampaignOption } from '../scenario-steps/run-scenario-editor';
import { StepCard } from './step-card';
import { BracketBlock } from './bracket-block';
import { InsertGap } from './insert-button';
import { StepDetailPanel } from './step-detail-panel';
import type { SelectorPickTarget } from './selector-pick';
import {
  selectorPickTargetEquals,
  isSelectorPickableStep
} from './selector-pick';
import type { CoordinatePickTarget } from './coordinate-pick';
import {
  coordinatePickTargetEquals,
  isTapCoordinatePickableStep,
  isSwipeCoordinatePickableStep
} from './coordinate-pick';
import { encodeFlowListRef, stableStepDnDId } from './flow-dnd-ids';
import { applyFlowDragEnd } from './flow-tree-dnd';
import { SortableFlowRow } from './sortable-flow-row';
import { FlowStepRail } from './flow-step-rail';
import { encodeScenarioInlineRunKey } from './inline-run-key';

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
  /** Pick tap_ratio / tap.fallback / swipe_ratio coordinates from device mirror. */
  coordinatePickTarget?: CoordinatePickTarget | null;
  onCoordinatePickTargetChange?: (target: CoordinatePickTarget | null) => void;
  /** Run a single step or control-flow subtree on the device inline (`runKey` = stable id for UI). */
  onRunStep?: (step: FlowStep, runKey: string) => void;
  /** Per-step / per-block run state from the parent (keys from `encodeScenarioInlineRunKey`). */
  stepRunStates?: Record<string, 'idle' | 'running' | 'ok' | 'error'>;
  /** Abort current inline preview. */
  onStopInlineRun?: () => void;
  /** When FlowEditor is inside another Radix Dialog (e.g. template editor). */
  nestedInDialog?: boolean;
  /** Other scenarios in the same campaign — powers run_scenario picker in the step panel. */
  campaignScenarios?: RunScenarioCampaignOption[];
}

const ROOT_SORTABLE_ID = encodeFlowListRef({ kind: 'root' });

export function FlowEditor({
  steps,
  onChange,
  maxHeight = '500px',
  compact = false,
  selectorPickTarget = null,
  onSelectorPickTargetChange,
  coordinatePickTarget = null,
  onCoordinatePickTargetChange,
  onRunStep,
  stepRunStates = {},
  onStopInlineRun,
  nestedInDialog = false,
  campaignScenarios = []
}: Props) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const selectedStep = selectedIndex != null ? steps[selectedIndex] : null;
  const availableVariables = useMemo(
    () => collectVariableNames(steps),
    [steps]
  );

  const stepIds = useMemo(
    () => steps.map((s, i) => stableStepDnDId(s, i)),
    [steps]
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      const activeContainer = active.data.current?.sortable?.containerId as
        | string
        | undefined;
      const overContainer = over?.data.current?.sortable?.containerId as
        | string
        | undefined;
      if (
        activeContainer === ROOT_SORTABLE_ID &&
        overContainer === ROOT_SORTABLE_ID &&
        over &&
        active.id !== over.id
      ) {
        const oldIndex = stepIds.indexOf(active.id as string);
        const newIndex = stepIds.indexOf(over.id as string);
        if (oldIndex >= 0 && newIndex >= 0) {
          setSelectedIndex((prev) => {
            if (prev === oldIndex) return newIndex;
            if (prev == null) return prev;
            if (oldIndex < prev && newIndex >= prev) return prev - 1;
            if (oldIndex > prev && newIndex <= prev) return prev + 1;
            return prev;
          });
        }
      }
      applyFlowDragEnd(event, steps, onChange);
    },
    [stepIds, steps, onChange]
  );

  const togglePick = useCallback(
    (path: SelectorPickTarget) => {
      if (!onSelectorPickTargetChange) return;
      onCoordinatePickTargetChange?.(null);
      onSelectorPickTargetChange(
        selectorPickTargetEquals(selectorPickTarget, path) ? null : path
      );
    },
    [
      onSelectorPickTargetChange,
      selectorPickTarget,
      onCoordinatePickTargetChange
    ]
  );

  const toggleCoordPick = useCallback(
    (path: CoordinatePickTarget) => {
      if (!onCoordinatePickTargetChange) return;
      onSelectorPickTargetChange?.(null);
      onCoordinatePickTargetChange(
        coordinatePickTargetEquals(coordinatePickTarget, path) ? null : path
      );
    },
    [
      onCoordinatePickTargetChange,
      coordinatePickTarget,
      onSelectorPickTargetChange
    ]
  );

  const handleLeafStepCardClick = useCallback(
    (i: number) => {
      if (compact) return;
      const isSelPick =
        onSelectorPickTargetChange &&
        selectorPickTarget &&
        selectorPickTarget.rootIndex === i &&
        (selectorPickTarget.path ?? []).length === 0;
      const isCoordPick =
        onCoordinatePickTargetChange &&
        coordinatePickTarget &&
        coordinatePickTarget.rootIndex === i &&
        (coordinatePickTarget.path ?? []).length === 0;

      // UX promise: click the same step again to cancel the active pick.
      if (isSelPick) onSelectorPickTargetChange(null);
      if (isCoordPick) onCoordinatePickTargetChange(null);

      setSelectedIndex(selectedIndex === i ? null : i);
    },
    [
      compact,
      onSelectorPickTargetChange,
      selectorPickTarget,
      onCoordinatePickTargetChange,
      coordinatePickTarget,
      selectedIndex
    ]
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.key === 'Escape' &&
        selectorPickTarget &&
        onSelectorPickTargetChange
      ) {
        onSelectorPickTargetChange(null);
      }
      if (
        e.key === 'Escape' &&
        coordinatePickTarget &&
        onCoordinatePickTargetChange
      ) {
        onCoordinatePickTargetChange(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [
    selectorPickTarget,
    onSelectorPickTargetChange,
    coordinatePickTarget,
    onCoordinatePickTargetChange
  ]);

  const insertAt = useCallback(
    (index: number, newStep: FlowStep) => {
      const next = [...steps];
      next.splice(index, 0, newStep);
      onChange(next);
    },
    [steps, onChange]
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
      if (
        onCoordinatePickTargetChange &&
        coordinatePickTarget?.rootIndex === index
      ) {
        onCoordinatePickTargetChange(null);
      }
    },
    [
      steps,
      onChange,
      selectedIndex,
      selectorPickTarget,
      onSelectorPickTargetChange,
      coordinatePickTarget,
      onCoordinatePickTargetChange
    ]
  );

  const updateAt = useCallback(
    (index: number, newStep: FlowStep) => {
      const next = [...steps];
      next[index] = newStep;
      onChange(next);
    },
    [steps, onChange]
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
          steps: branches[bi].steps.filter(
            (_: unknown, i: number) => i !== childIndex
          )
        };
        next.branches = branches;
      } else {
        next[key] = (next[key] ?? []).filter(
          (_: unknown, i: number) => i !== childIndex
        );
      }
      updateAt(parentIndex, next);
    },
    [steps, updateAt]
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
    [steps, updateAt]
  );

  return (
    <>
      <Dialog
        open={!compact && selectedIndex != null}
        onOpenChange={(open) => {
          if (!open) setSelectedIndex(null);
        }}
      >
        <DialogContent className='max-w-sm gap-0 p-0'>
          <DialogHeader className='sr-only'>
            <DialogTitle>Chỉnh sửa bước</DialogTitle>
          </DialogHeader>
          {selectedStep && selectedIndex != null && (
            <StepDetailPanel
              step={selectedStep}
              onChange={(s) => updateAt(selectedIndex, s)}
              onClose={() => setSelectedIndex(null)}
              availableVariables={availableVariables}
              campaignScenarios={campaignScenarios}
              onRequestPickSelector={
                onSelectorPickTargetChange
                  ? () => {
                      const idx = selectedIndex;
                      setSelectedIndex(null);
                      onCoordinatePickTargetChange?.(null);
                      onSelectorPickTargetChange({ rootIndex: idx, path: [] });
                    }
                  : undefined
              }
              onRequestPickTapCoords={
                onCoordinatePickTargetChange &&
                (selectedStep.type === 'tap_ratio' ||
                  selectedStep.type === 'tap')
                  ? () => {
                      const idx = selectedIndex;
                      setSelectedIndex(null);
                      onSelectorPickTargetChange?.(null);
                      onCoordinatePickTargetChange({
                        rootIndex: idx,
                        path: [],
                        mode: 'tap_point'
                      });
                    }
                  : undefined
              }
              onRequestPickSwipeCoords={
                onCoordinatePickTargetChange &&
                selectedStep.type === 'swipe_ratio'
                  ? () => {
                      const idx = selectedIndex;
                      setSelectedIndex(null);
                      onSelectorPickTargetChange?.(null);
                      onCoordinatePickTargetChange({
                        rootIndex: idx,
                        path: [],
                        mode: 'swipe_segment'
                      });
                    }
                  : undefined
              }
            />
          )}
        </DialogContent>
      </Dialog>

      <div className='min-w-0'>
        <div
          className='min-w-0 overflow-y-auto overflow-x-hidden'
          style={{ maxHeight }}
        >
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
            modifiers={[restrictToVerticalAxis]}
          >
            <SortableContext
              id={ROOT_SORTABLE_ID}
              items={stepIds}
              strategy={verticalListSortingStrategy}
            >
              {steps.map((step, i) => (
                <div key={stepIds[i]}>
                  <InsertGap onInsert={(s) => insertAt(i, s)} />
                  <SortableFlowRow id={stepIds[i]!}>
                    {(dragHandle, isDragging) => (
                      <div
                        className={`flex items-stretch ${isDragging ? 'opacity-60' : ''}`}
                      >
                        {dragHandle}
                        <FlowStepRail
                          stepNumber={i + 1}
                          showLine={i < steps.length - 1}
                        />
                        <div className='min-w-0 flex-1'>
                          {isContainerType(step.type) ? (
                            <BracketBlock
                              step={step}
                              stepIndex={i}
                              rootStepIndex={i}
                              pathFromRoot={[]}
                              selected={selectedIndex === i}
                              selectedChild={null}
                              onSelectSelf={() =>
                                setSelectedIndex(selectedIndex === i ? null : i)
                              }
                              onSelectChild={() => {}}
                              onUpdate={(s) => updateAt(i, s)}
                              onRemove={() => removeAt(i)}
                              onRemoveChild={(key, ci) =>
                                removeChild(i, key, ci)
                              }
                              onInsertChild={(key, at, s) =>
                                insertChild(i, key, at, s)
                              }
                              compact={compact}
                              nestedInDialog={nestedInDialog}
                              selectorPickTarget={selectorPickTarget}
                              onTogglePickSelector={
                                onSelectorPickTargetChange
                                  ? togglePick
                                  : undefined
                              }
                              coordinatePickTarget={coordinatePickTarget}
                              onToggleCoordinatePick={
                                onCoordinatePickTargetChange
                                  ? toggleCoordPick
                                  : undefined
                              }
                              selfRunKey={encodeScenarioInlineRunKey(i, [])}
                              stepRunStates={stepRunStates}
                              onStopInlineRun={onStopInlineRun}
                              onRunSelf={
                                onRunStep
                                  ? () =>
                                      onRunStep(
                                        step,
                                        encodeScenarioInlineRunKey(i, [])
                                      )
                                  : undefined
                              }
                              onRunChild={
                                onRunStep
                                  ? (s, k) => onRunStep(s, k)
                                  : undefined
                              }
                              campaignScenarios={campaignScenarios}
                            />
                          ) : (
                            <StepCard
                              step={step}
                              index={i}
                              selected={!compact && selectedIndex === i}
                              compact={compact}
                              onClick={() => handleLeafStepCardClick(i)}
                              onRemove={() => removeAt(i)}
                              onRun={
                                onRunStep
                                  ? () =>
                                      onRunStep(
                                        step,
                                        encodeScenarioInlineRunKey(i, [])
                                      )
                                  : undefined
                              }
                              runState={stepRunStates[String(i)] ?? 'idle'}
                              onStopInlineRun={onStopInlineRun}
                              isPickTarget={
                                selectorPickTarget != null &&
                                selectorPickTarget.rootIndex === i &&
                                (selectorPickTarget.path ?? []).length === 0
                              }
                              onTogglePickSelector={
                                onSelectorPickTargetChange &&
                                isSelectorPickableStep(step)
                                  ? () => togglePick({ rootIndex: i, path: [] })
                                  : undefined
                              }
                              coordPickActive={
                                coordinatePickTarget &&
                                coordinatePickTargetEquals(
                                  coordinatePickTarget,
                                  {
                                    rootIndex: i,
                                    path: [],
                                    mode: 'tap_point'
                                  }
                                )
                                  ? 'tap_point'
                                  : coordinatePickTarget &&
                                      coordinatePickTargetEquals(
                                        coordinatePickTarget,
                                        {
                                          rootIndex: i,
                                          path: [],
                                          mode: 'swipe_segment'
                                        }
                                      )
                                    ? 'swipe_segment'
                                    : null
                              }
                              onTogglePickTapCoords={
                                onCoordinatePickTargetChange &&
                                isTapCoordinatePickableStep(step)
                                  ? () =>
                                      toggleCoordPick({
                                        rootIndex: i,
                                        path: [],
                                        mode: 'tap_point'
                                      })
                                  : undefined
                              }
                              onTogglePickSwipeCoords={
                                onCoordinatePickTargetChange &&
                                isSwipeCoordinatePickableStep(step)
                                  ? () =>
                                      toggleCoordPick({
                                        rootIndex: i,
                                        path: [],
                                        mode: 'swipe_segment'
                                      })
                                  : undefined
                              }
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </SortableFlowRow>
                </div>
              ))}
              <InsertGap onInsert={(s) => insertAt(steps.length, s)} />
            </SortableContext>
          </DndContext>

          {steps.length === 0 && (
            <p className='py-6 text-center text-xs text-muted-foreground'>
              Nhấn <strong>+</strong> để thêm bước, hoặc ghi thao tác từ thiết
              bị.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

function collectVariableNames(steps: FlowStep[]): string[] {
  const names = new Set<string>();

  const collectFromStep = (step: FlowStep) => {
    if (step.type === 'set_variable' && step.name?.trim()) {
      names.add(step.name.trim());
    }
    if (step.type === 'if_variable' && step.name?.trim()) {
      names.add(step.name.trim());
    }
    if (step.type === 'set_var' && step.key?.trim()) {
      names.add(step.key.trim());
    }
    if (step.type === 'run_scenario' && step.variables) {
      Object.keys(step.variables).forEach((k) => {
        if (k.trim()) names.add(k.trim());
      });
    }

    if ('steps' in step && Array.isArray(step.steps)) {
      step.steps.forEach(collectFromStep);
    }
    if ('then' in step && Array.isArray(step.then)) {
      step.then.forEach(collectFromStep);
    }
    if ('else' in step && Array.isArray(step.else)) {
      step.else.forEach(collectFromStep);
    }
    if ('branches' in step && Array.isArray(step.branches)) {
      step.branches.forEach((branch) => {
        if (Array.isArray(branch.steps)) {
          branch.steps.forEach(collectFromStep);
        }
      });
    }
  };

  steps.forEach(collectFromStep);
  return Array.from(names).sort((a, b) => a.localeCompare(b));
}
