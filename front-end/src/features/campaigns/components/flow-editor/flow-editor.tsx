'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
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
import { useVirtualizer } from '@tanstack/react-virtual';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { isContainerType, type FlowStep } from '../scenario-steps/types';
import type { RunScenarioCampaignOption } from '../scenario-steps/run-scenario-editor';
import { StepCard } from './step-card';
import { BracketBlock } from './bracket-block';
import { InsertGap } from './insert-button';
import { InsertStepPicker } from './insert-step-picker';
import {
  primaryProducedVariable,
  variablesProducedByStep
} from './step-produced-variables';
import { StepRunResultStrip, type StepRunResult } from './step-run-result';
import { UseResultActions } from './use-result-actions';
import {
  StepDetailPanel,
  type SessionGateRuntimeContext
} from './step-detail-panel';
import { useMirrorStepActions } from './use-mirror-step-actions';
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
import { FlowEditorEditSessionProvider } from './flow-editor-edit-session';
import type { VariablePreviewValues } from './variable-preview';
import {
  resolveStepAtPath,
  updateStepAtPath,
  type BracketChildRef
} from './step-tree-walk';
import { insertStepAtPath } from './insert-step-at-path';
import { projectVirtualFlowRows } from './virtual-flow-rows';

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
  /** Parent dialog can set modal={false} while a nested child step editor is open. */
  onChildStepEditorOpenChange?: (open: boolean) => void;
  /** Other scenarios in the same campaign — powers run_scenario picker in the step panel. */
  campaignScenarios?: RunScenarioCampaignOption[];
  /** Variables declared outside the step tree, e.g. scenario/global variables. */
  availableVariables?: string[];
  /** Values used only for UI previews of ${VAR}; execution still uses raw step data. */
  variablePreviewValues?: VariablePreviewValues;
  /** Enable drag-and-drop registration. Heavy control surfaces can disable it until the user enters sort mode. */
  enableDragDrop?: boolean;
  /** What each step produced on its last inline run, keyed by runKey. */
  stepRunResults?: Record<string, StepRunResult>;
  /** Show lightweight reorder controls in the virtualized editor. */
  virtualReorderMode?: boolean;
  sessionGateRuntimeContext?: SessionGateRuntimeContext;
}

const ROOT_SORTABLE_ID = encodeFlowListRef({ kind: 'root' });
const EMPTY_AVAILABLE_VARIABLES: string[] = [];

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
  onChildStepEditorOpenChange,
  campaignScenarios = [],
  availableVariables: externalAvailableVariables = EMPTY_AVAILABLE_VARIABLES,
  variablePreviewValues,
  sessionGateRuntimeContext,
  enableDragDrop = true,
  stepRunResults,
  virtualReorderMode = false
}: Props) {
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const pendingDetailRef = useRef<FlowStep | null>(null);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;
  const selectedStep = selectedIndex != null ? steps[selectedIndex] : null;

  const handleDetailPanelChange = useCallback((s: FlowStep) => {
    pendingDetailRef.current = s;
  }, []);

  useEffect(() => {
    if (selectedIndex == null) {
      pendingDetailRef.current = null;
      return;
    }
    const step = stepsRef.current[selectedIndex];
    if (step) pendingDetailRef.current = step;
  }, [selectedIndex]);
  const availableVariables = useMemo(
    () =>
      Array.from(
        new Set([
          ...externalAvailableVariables
            .map((name) => name.trim())
            .filter(Boolean),
          ...collectVariableNames(steps)
        ])
      ).sort((a, b) => a.localeCompare(b)),
    [externalAvailableVariables, steps]
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
      const next = [...stepsRef.current];
      next.splice(index, 0, newStep);
      onChange(next);
    },
    [onChange]
  );

  const removeAt = useCallback(
    (index: number) => {
      onChange(stepsRef.current.filter((_, i) => i !== index));
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
      const next = [...stepsRef.current];
      next[index] = newStep;
      onChange(next);
    },
    [onChange]
  );

  const closeDetailForCrop = useCallback(() => {
    if (pendingDetailRef.current != null && selectedIndex != null) {
      updateAt(selectedIndex, pendingDetailRef.current);
    }
    pendingDetailRef.current = null;
    setSelectedIndex(null);
  }, [selectedIndex, updateAt]);

  const mirrorActions = useMirrorStepActions(() => {
    const idx = selectedIndex;
    if (idx == null) return null;
    const step = pendingDetailRef.current ?? stepsRef.current[idx];
    if (!step) return null;
    return { step, apply: (next) => updateAt(idx, next) };
  }, closeDetailForCrop);

  const removeChild = useCallback(
    (parentIndex: number, key: string, childIndex: number) => {
      const parent = stepsRef.current[parentIndex];
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
    [updateAt]
  );

  const insertChild = useCallback(
    (parentIndex: number, key: string, at: number, newStep: FlowStep) => {
      const parent = stepsRef.current[parentIndex];
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
    [updateAt]
  );

  if (!enableDragDrop) {
    return (
      <FlowEditorEditSessionProvider
        onChildStepEditorOpenChange={onChildStepEditorOpenChange}
      >
        <VirtualizedFlowEditor
          steps={steps}
          onChange={onChange}
          maxHeight={maxHeight}
          compact={compact}
          selectorPickTarget={selectorPickTarget}
          onSelectorPickTargetChange={onSelectorPickTargetChange}
          coordinatePickTarget={coordinatePickTarget}
          onCoordinatePickTargetChange={onCoordinatePickTargetChange}
          onRunStep={onRunStep}
          stepRunStates={stepRunStates}
          onStopInlineRun={onStopInlineRun}
          campaignScenarios={campaignScenarios}
          sessionGateRuntimeContext={sessionGateRuntimeContext}
          availableVariables={availableVariables}
          variablePreviewValues={variablePreviewValues}
          reorderMode={virtualReorderMode}
          stepRunResults={stepRunResults}
        />
      </FlowEditorEditSessionProvider>
    );
  }

  const editorBody = (
    <>
      <Dialog
        open={!compact && selectedIndex != null}
        onOpenChange={(open) => {
          if (!open) {
            if (pendingDetailRef.current != null && selectedIndex != null) {
              updateAt(selectedIndex, pendingDetailRef.current);
            }
            pendingDetailRef.current = null;
            setSelectedIndex(null);
          }
        }}
      >
        <DialogContent className='max-w-sm gap-0 p-0'>
          <DialogHeader className='sr-only'>
            <DialogTitle>{tField('editStepTitle')}</DialogTitle>
          </DialogHeader>
          {selectedStep && selectedIndex != null && (
            <StepDetailPanel
              step={selectedStep}
              onChange={handleDetailPanelChange}
              onClose={() => {
                if (pendingDetailRef.current != null && selectedIndex != null) {
                  updateAt(selectedIndex, pendingDetailRef.current);
                }
                pendingDetailRef.current = null;
                setSelectedIndex(null);
              }}
              availableVariables={availableVariables}
              variablePreviewValues={variablePreviewValues}
              campaignScenarios={campaignScenarios}
              runtimeContext={sessionGateRuntimeContext}
              onRequestCropImage={mirrorActions.cropImage}
              onRequestPickRegion={mirrorActions.pickRegion}
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
          className='group/flowlist min-w-0 overflow-y-auto overflow-x-hidden'
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
                      <FlowEditorRow
                        campaignScenarios={campaignScenarios}
                        sessionGateRuntimeContext={sessionGateRuntimeContext}
                        compact={compact}
                        coordinatePickTarget={coordinatePickTarget}
                        dragHandle={dragHandle}
                        enableDragDrop={enableDragDrop}
                        handleLeafStepCardClick={handleLeafStepCardClick}
                        index={i}
                        insertChild={insertChild}
                        isDragging={isDragging}
                        nestedInDialog={nestedInDialog}
                        availableVariables={availableVariables}
                        variablePreviewValues={variablePreviewValues}
                        onCoordinatePickTargetChange={
                          onCoordinatePickTargetChange
                        }
                        onRunStep={onRunStep}
                        onSelectorPickTargetChange={onSelectorPickTargetChange}
                        onStopInlineRun={onStopInlineRun}
                        removeAt={removeAt}
                        removeChild={removeChild}
                        selectedIndex={selectedIndex}
                        selectorPickTarget={selectorPickTarget}
                        setSelectedIndex={setSelectedIndex}
                        step={step}
                        stepCount={steps.length}
                        stepRunStates={stepRunStates}
                        toggleCoordPick={toggleCoordPick}
                        togglePick={togglePick}
                        updateAt={updateAt}
                      />
                    )}
                  </SortableFlowRow>
                </div>
              ))}
              <InsertGap
                persistent
                onInsert={(s) => insertAt(stepsRef.current.length, s)}
              />
            </SortableContext>
          </DndContext>

          {steps.length === 0 && (
            <p className='py-6 text-center text-xs text-muted-foreground'>
              {tField('emptyFlowHint')}
            </p>
          )}
        </div>
      </div>
    </>
  );

  return (
    <FlowEditorEditSessionProvider
      onChildStepEditorOpenChange={onChildStepEditorOpenChange}
    >
      {editorBody}
    </FlowEditorEditSessionProvider>
  );
}

function pathKey(path: BracketChildRef[]): string {
  return path.map((seg) => `${seg.listKey}:${seg.ci}`).join('/');
}

function targetFromPath(path: BracketChildRef[]): SelectorPickTarget {
  const root = path[0]!;
  return {
    rootIndex: root.ci,
    path: path.slice(1).map((seg) => ({
      listKey: seg.listKey,
      childIndex: seg.ci
    }))
  };
}

function runKeyFromPath(path: BracketChildRef[]): string {
  const target = targetFromPath(path);
  return encodeScenarioInlineRunKey(target.rootIndex, target.path);
}

function outlineNumber(path: BracketChildRef[]): string {
  return path.map((seg) => String(seg.ci + 1)).join('.');
}

function localStepNumber(path: BracketChildRef[]): string {
  return String((path.at(-1)?.ci ?? 0) + 1);
}

function removeStepAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[]
): FlowStep[] {
  if (!path.length) return rootSteps;
  if (path.length === 1) {
    return rootSteps.filter((_, i) => i !== path[0]!.ci);
  }
  const parentPath = path.slice(0, -1);
  const last = path[path.length - 1]!;
  const parent = resolveStepAtPath(rootSteps, parentPath);
  if (!parent) return rootSteps;
  const nextParent = { ...parent } as Record<string, unknown>;
  if (last.listKey.startsWith('branches.')) {
    const bi = Number.parseInt(last.listKey.split('.')[1] ?? '0', 10);
    const branches = [
      ...((nextParent.branches as Array<{ steps?: FlowStep[] }>) ?? [])
    ];
    const branch = branches[bi];
    if (!branch) return rootSteps;
    branches[bi] = {
      ...branch,
      steps: (branch.steps ?? []).filter((_, i) => i !== last.ci)
    };
    nextParent.branches = branches;
  } else {
    nextParent[last.listKey] = (
      (nextParent[last.listKey] as FlowStep[] | undefined) ?? []
    ).filter((_, i) => i !== last.ci);
  }
  return updateStepAtPath(rootSteps, parentPath, nextParent as FlowStep);
}

function listAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[]
): FlowStep[] {
  if (path.length <= 1) return rootSteps;
  const parent = resolveStepAtPath(rootSteps, path.slice(0, -1));
  const last = path[path.length - 1];
  if (!parent || !last) return [];
  if (last.listKey.startsWith('branches.')) {
    const bi = Number.parseInt(last.listKey.split('.')[1] ?? '0', 10);
    return (
      (parent as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> })
        .branches?.[bi]?.steps ?? []
    );
  }
  return (
    ((parent as Record<string, unknown>)[last.listKey] as FlowStep[]) ?? []
  );
}

function moveWithinList(
  items: FlowStep[],
  from: number,
  to: number
): FlowStep[] {
  if (
    from === to ||
    from < 0 ||
    to < 0 ||
    from >= items.length ||
    to >= items.length
  ) {
    return items;
  }
  const next = [...items];
  const [item] = next.splice(from, 1);
  if (!item) return items;
  next.splice(to, 0, item);
  return next;
}

function moveStepAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[],
  delta: -1 | 1
): FlowStep[] {
  const last = path[path.length - 1];
  if (!last) return rootSteps;
  const to = last.ci + delta;
  if (path.length === 1) {
    return moveWithinList(rootSteps, last.ci, to);
  }

  const parentPath = path.slice(0, -1);
  const parent = resolveStepAtPath(rootSteps, parentPath);
  if (!parent) return rootSteps;
  const nextParent = { ...parent } as Record<string, unknown>;
  if (last.listKey.startsWith('branches.')) {
    const bi = Number.parseInt(last.listKey.split('.')[1] ?? '0', 10);
    const branches = [
      ...((nextParent.branches as Array<{ steps?: FlowStep[] }>) ?? [])
    ];
    const branch = branches[bi];
    if (!branch) return rootSteps;
    branches[bi] = {
      ...branch,
      steps: moveWithinList(branch.steps ?? [], last.ci, to)
    };
    nextParent.branches = branches;
  } else {
    nextParent[last.listKey] = moveWithinList(
      (nextParent[last.listKey] as FlowStep[] | undefined) ?? [],
      last.ci,
      to
    );
  }
  return updateStepAtPath(rootSteps, parentPath, nextParent as FlowStep);
}

function VirtualizedFlowEditor({
  steps,
  onChange,
  maxHeight,
  compact,
  selectorPickTarget,
  onSelectorPickTargetChange,
  coordinatePickTarget,
  onCoordinatePickTargetChange,
  onRunStep,
  stepRunStates,
  onStopInlineRun,
  campaignScenarios,
  sessionGateRuntimeContext,
  availableVariables,
  variablePreviewValues,
  reorderMode,
  stepRunResults
}: {
  steps: FlowStep[];
  onChange: (steps: FlowStep[]) => void;
  maxHeight: string;
  compact: boolean;
  selectorPickTarget: SelectorPickTarget | null;
  onSelectorPickTargetChange?: (target: SelectorPickTarget | null) => void;
  coordinatePickTarget: CoordinatePickTarget | null;
  onCoordinatePickTargetChange?: (target: CoordinatePickTarget | null) => void;
  onRunStep?: (step: FlowStep, runKey: string) => void;
  stepRunStates: Record<string, 'idle' | 'running' | 'ok' | 'error'>;
  onStopInlineRun?: () => void;
  campaignScenarios: RunScenarioCampaignOption[];
  sessionGateRuntimeContext?: SessionGateRuntimeContext;
  availableVariables: string[];
  variablePreviewValues?: VariablePreviewValues;
  reorderMode: boolean;
  stepRunResults?: Record<string, StepRunResult>;
}) {
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const parentRef = useRef<HTMLDivElement | null>(null);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;
  const [selectedPath, setSelectedPath] = useState<BracketChildRef[] | null>(
    null
  );
  const pendingDetailRef = useRef<FlowStep | null>(null);
  const rows = useMemo(() => projectVirtualFlowRows(steps), [steps]);
  const selectedStep = selectedPath
    ? resolveStepAtPath(steps, selectedPath)
    : null;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const row = rows[index];
      if (row?.kind !== 'step') return 38;
      const step = row.step;
      return isContainerType(step?.type ?? '') ? 78 : 64;
    },
    getItemKey: (index) => rows[index]?.key ?? index,
    overscan: 8
  });

  const updatePath = useCallback(
    (path: BracketChildRef[], step: FlowStep) => {
      onChange(updateStepAtPath(stepsRef.current, path, step));
    },
    [onChange]
  );

  const closeDetail = useCallback(() => {
    if (pendingDetailRef.current && selectedPath) {
      updatePath(selectedPath, pendingDetailRef.current);
    }
    pendingDetailRef.current = null;
    setSelectedPath(null);
  }, [selectedPath, updatePath]);

  const handleDetailPanelChange = useCallback((step: FlowStep) => {
    pendingDetailRef.current = step;
  }, []);

  const mirrorActions = useMirrorStepActions(() => {
    const path = selectedPath;
    if (!path) return null;
    const step = pendingDetailRef.current ?? resolveStepAtPath(steps, path);
    if (!step) return null;
    return { step, apply: (next) => updatePath(path, next) };
  }, closeDetail);

  const removePath = useCallback(
    (path: BracketChildRef[]) => {
      onChange(removeStepAtPath(stepsRef.current, path));
      setSelectedPath((current) =>
        current && pathKey(current) === pathKey(path) ? null : current
      );
    },
    [onChange]
  );
  const movePath = useCallback(
    (path: BracketChildRef[], delta: -1 | 1) => {
      onChange(moveStepAtPath(stepsRef.current, path, delta));
      setSelectedPath((current) => {
        if (!current || pathKey(current) !== pathKey(path)) return current;
        const next = [...current];
        const last = next[next.length - 1];
        if (last) next[next.length - 1] = { ...last, ci: last.ci + delta };
        return next;
      });
    },
    [onChange]
  );
  const insertBeforePath = useCallback(
    (path: BracketChildRef[], step: FlowStep) => {
      onChange(insertStepAtPath(stepsRef.current, path, step));
    },
    [onChange]
  );

  /** insertStepAtPath splices *at* the index, so +1 lands after the step. */
  const insertAfterPath = useCallback(
    (path: BracketChildRef[], step: FlowStep) => {
      const last = path[path.length - 1];
      if (!last) return;
      const after = [...path.slice(0, -1), { ...last, ci: last.ci + 1 }];
      onChange(insertStepAtPath(stepsRef.current, after, step));
    },
    [onChange]
  );

  return (
    <>
      <Dialog
        open={!compact && selectedPath != null}
        onOpenChange={(open) => {
          if (!open) closeDetail();
        }}
      >
        <DialogContent className='max-w-sm gap-0 p-0'>
          <DialogHeader className='sr-only'>
            <DialogTitle>{tField('editStepTitle')}</DialogTitle>
          </DialogHeader>
          {selectedStep && selectedPath && (
            <StepDetailPanel
              step={selectedStep}
              onChange={handleDetailPanelChange}
              onClose={closeDetail}
              availableVariables={availableVariables}
              variablePreviewValues={variablePreviewValues}
              campaignScenarios={campaignScenarios}
              runtimeContext={sessionGateRuntimeContext}
              onRequestCropImage={mirrorActions.cropImage}
              onRequestPickRegion={mirrorActions.pickRegion}
              onRequestPickSelector={
                onSelectorPickTargetChange
                  ? () => {
                      onCoordinatePickTargetChange?.(null);
                      onSelectorPickTargetChange(targetFromPath(selectedPath));
                      setSelectedPath(null);
                    }
                  : undefined
              }
              onRequestPickTapCoords={
                onCoordinatePickTargetChange &&
                (selectedStep.type === 'tap_ratio' ||
                  selectedStep.type === 'tap')
                  ? () => {
                      onSelectorPickTargetChange?.(null);
                      onCoordinatePickTargetChange({
                        ...targetFromPath(selectedPath),
                        mode: 'tap_point'
                      });
                      setSelectedPath(null);
                    }
                  : undefined
              }
              onRequestPickSwipeCoords={
                onCoordinatePickTargetChange &&
                selectedStep.type === 'swipe_ratio'
                  ? () => {
                      onSelectorPickTargetChange?.(null);
                      onCoordinatePickTargetChange({
                        ...targetFromPath(selectedPath),
                        mode: 'swipe_segment'
                      });
                      setSelectedPath(null);
                    }
                  : undefined
              }
            />
          )}
        </DialogContent>
      </Dialog>

      <div
        className='flex min-h-0 w-full flex-col'
        style={{ height: maxHeight === '100%' ? '100%' : undefined }}
      >
        <div
          ref={parentRef}
          className='group/flowlist min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-muted/[0.12]'
          style={{ maxHeight: maxHeight === '100%' ? undefined : maxHeight }}
        >
          <div
            className='relative w-full'
            style={{ height: `${virtualizer.getTotalSize()}px` }}
          >
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index];
              if (!row) return null;
              if (row.kind !== 'step') {
                return (
                  <div
                    key={virtualRow.key}
                    ref={virtualizer.measureElement}
                    data-index={virtualRow.index}
                    className='absolute left-0 top-0 w-full px-1.5 py-1'
                    style={{ transform: `translateY(${virtualRow.start}px)` }}
                  >
                    <VirtualScopeMarker
                      row={row}
                      onInsert={
                        !reorderMode && row.kind === 'branch'
                          ? (step) => insertBeforePath(row.insertPath, step)
                          : undefined
                      }
                    />
                  </div>
                );
              }
              const target = targetFromPath(row.path);
              const runKey = runKeyFromPath(row.path);
              const runResult = stepRunResults?.[runKey];
              const producedVar = primaryProducedVariable(row.step);
              const selected =
                selectedPath != null &&
                pathKey(selectedPath) === pathKey(row.path);
              const coordPickActive =
                coordinatePickTarget &&
                coordinatePickTargetEquals(coordinatePickTarget, {
                  ...target,
                  mode: 'tap_point'
                })
                  ? 'tap_point'
                  : coordinatePickTarget &&
                      coordinatePickTargetEquals(coordinatePickTarget, {
                        ...target,
                        mode: 'swipe_segment'
                      })
                    ? 'swipe_segment'
                    : null;
              const siblingCount = listAtPath(steps, row.path).length;
              const childIndex = row.path[row.path.length - 1]?.ci ?? 0;
              const canMoveUp = childIndex > 0;
              const canMoveDown = childIndex < siblingCount - 1;
              return (
                <div
                  key={virtualRow.key}
                  ref={virtualizer.measureElement}
                  data-index={virtualRow.index}
                  className='absolute left-0 top-0 w-full px-1.5 py-1'
                  style={{
                    transform: `translateY(${virtualRow.start}px)`
                  }}
                >
                  <div className='flex min-w-0 items-stretch gap-2'>
                    <VirtualFlowStepRail
                      label={localStepNumber(row.path)}
                      fullLabel={outlineNumber(row.path)}
                      showLine={virtualRow.index < rows.length - 1}
                      root={row.depth === 0}
                    />
                    <VirtualBranchRail
                      listKey={row.path.at(-1)?.listKey}
                      depth={row.depth}
                    />
                    <div
                      className='min-w-0 flex-1'
                      style={{
                        paddingLeft: row.depth > 0 ? '4px' : undefined
                      }}
                    >
                      {!reorderMode ? (
                        <div className='group/insert mb-1 flex h-4 items-center gap-1.5'>
                          <span className='h-px min-w-0 flex-1 bg-border/0 transition-colors group-hover/insert:bg-border/70' />
                          <InsertStepPicker
                            contentSide='bottom'
                            contentAlign='center'
                            sideOffset={4}
                            onInsert={(step) =>
                              insertBeforePath(row.path, step)
                            }
                            trigger={
                              <button
                                type='button'
                                className='flex h-5 items-center rounded-full border border-border/0 px-2 text-[10px] font-medium text-muted-foreground/0 transition-all hover:border-border hover:bg-background hover:text-primary focus-visible:border-border focus-visible:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/flowlist:border-border/40 group-hover/insert:border-border/70 group-hover/insert:bg-background group-hover/flowlist:text-muted-foreground/60 group-hover/insert:text-muted-foreground'
                                aria-label={tField('addStepBefore', {
                                  number: outlineNumber(row.path)
                                })}
                              >
                                {tField('addHere')}
                              </button>
                            }
                          />
                          <span className='h-px min-w-0 flex-1 bg-border/0 transition-colors group-hover/insert:bg-border/70' />
                        </div>
                      ) : null}
                      <StepCard
                        step={row.step}
                        index={virtualRow.index}
                        selected={!compact && selected}
                        compact={compact}
                        onClick={() => {
                          if (compact) return;
                          setSelectedPath(selected ? null : row.path);
                        }}
                        onRemove={() => removePath(row.path)}
                        onRun={
                          onRunStep
                            ? () => onRunStep(row.step, runKey)
                            : undefined
                        }
                        runState={stepRunStates[runKey] ?? 'idle'}
                        onStopInlineRun={onStopInlineRun}
                        isPickTarget={
                          selectorPickTarget != null &&
                          selectorPickTargetEquals(selectorPickTarget, target)
                        }
                        onTogglePickSelector={
                          onSelectorPickTargetChange &&
                          isSelectorPickableStep(row.step)
                            ? () =>
                                onSelectorPickTargetChange(
                                  selectorPickTargetEquals(
                                    selectorPickTarget,
                                    target
                                  )
                                    ? null
                                    : target
                                )
                            : undefined
                        }
                        coordPickActive={coordPickActive}
                        onTogglePickTapCoords={
                          onCoordinatePickTargetChange &&
                          isTapCoordinatePickableStep(row.step)
                            ? () =>
                                onCoordinatePickTargetChange(
                                  coordPickActive === 'tap_point'
                                    ? null
                                    : { ...target, mode: 'tap_point' }
                                )
                            : undefined
                        }
                        onTogglePickSwipeCoords={
                          onCoordinatePickTargetChange &&
                          isSwipeCoordinatePickableStep(row.step)
                            ? () =>
                                onCoordinatePickTargetChange(
                                  coordPickActive === 'swipe_segment'
                                    ? null
                                    : { ...target, mode: 'swipe_segment' }
                                )
                            : undefined
                        }
                        reorderControls={
                          reorderMode
                            ? {
                                canMoveUp,
                                canMoveDown,
                                onMoveUp: () => movePath(row.path, -1),
                                onMoveDown: () => movePath(row.path, 1)
                              }
                            : undefined
                        }
                        variablePreviewValues={variablePreviewValues}
                      />
                      {runResult && (
                        <StepRunResultStrip
                          result={runResult}
                          action={
                            producedVar ? (
                              <UseResultActions
                                variable={producedVar}
                                onInsert={(next) =>
                                  insertAfterPath(row.path, next)
                                }
                              />
                            ) : undefined
                          }
                        />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {rows.length === 0 && (
            <p className='py-6 text-center text-xs text-muted-foreground'>
              {tField('emptyFlowHint')}
            </p>
          )}
        </div>

        {/* Always-visible append action. The per-row "add here" controls are
          hover-only and there was nothing at all after the last step, so the
          panel read as having no way to add anything. This sits outside the
          scroll area so it stays reachable however long the list gets. */}
        {!reorderMode && (
          <div className='shrink-0 border-t border-border/60 bg-background px-1.5 py-1.5'>
            <InsertStepPicker
              contentSide='top'
              contentAlign='center'
              sideOffset={6}
              onInsert={(step) => onChange([...steps, step])}
              trigger={
                <Button
                  type='button'
                  variant='outline'
                  className='h-8 w-full justify-center gap-1.5 rounded-md border-dashed border-muted-foreground/40 text-xs font-medium text-muted-foreground hover:border-primary/60 hover:bg-primary/5 hover:text-primary'
                >
                  <Plus className='size-3.5' strokeWidth={2} />
                  {tField('addStep')}
                </Button>
              }
            />
          </div>
        )}
      </div>
    </>
  );
}

function VirtualFlowStepRail({
  label,
  fullLabel,
  showLine,
  root
}: {
  label: string;
  fullLabel: string;
  showLine: boolean;
  root: boolean;
}) {
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  return (
    <div className='flex w-9 shrink-0 flex-col items-center pt-1.5'>
      {root ? (
        <span
          className='flex size-6 items-center justify-center rounded-full border border-border/70 bg-background text-[10px] font-bold tabular-nums text-foreground/65 shadow-sm'
          title={tField('stepNumber', { number: fullLabel })}
          aria-label={tField('stepNumber', { number: fullLabel })}
        >
          {label}
        </span>
      ) : (
        <span className='h-6' aria-hidden />
      )}
      {showLine && (
        <div
          className={cn(
            'mt-1 min-h-[10px] w-px flex-1',
            root ? 'bg-border/60' : 'bg-transparent'
          )}
        />
      )}
    </div>
  );
}

function VirtualBranchRail({
  listKey,
  depth
}: {
  listKey?: string;
  depth: number;
}) {
  if (!listKey || depth === 0) return null;
  const color =
    listKey === 'then'
      ? 'bg-emerald-500/55'
      : listKey === 'else'
        ? 'bg-rose-500/45'
        : listKey.startsWith('branches.')
          ? 'bg-violet-500/50'
          : 'bg-teal-500/50';
  return (
    <div className='relative w-2 shrink-0 self-stretch' aria-hidden>
      <span
        className={`absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full ${color}`}
      />
    </div>
  );
}

function VirtualScopeMarker({
  row,
  onInsert
}: {
  row: Exclude<
    ReturnType<typeof projectVirtualFlowRows>[number],
    { kind: 'step' }
  >;
  onInsert?: (step: FlowStep) => void;
}) {
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const conditional = row.scopes.at(-1)?.type;
  const isElse = row.kind === 'branch' && row.branch === 'else';
  const isThen = row.kind === 'branch' && row.branch === 'then';
  const marker = row.kind === 'end' ? '└' : isThen ? '✓' : isElse ? '×' : '↻';
  const addHereLabel = tField('addHere').replace(/^\+\s*/, '');

  return (
    <div className='flex min-h-8 min-w-0 items-stretch gap-2'>
      <div className='w-9 shrink-0' />
      <div
        className={cn(
          'relative w-2 shrink-0 self-stretch',
          row.kind === 'end' && 'opacity-70'
        )}
        aria-hidden
      >
        <span
          className={cn(
            'absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full',
            isThen
              ? 'bg-emerald-500/55'
              : isElse
                ? 'bg-rose-500/45'
                : row.kind === 'end'
                  ? 'bg-amber-500/45'
                  : 'bg-teal-500/50'
          )}
        />
      </div>
      <div className='min-w-0 flex-1'>
        <div
          className={cn(
            'flex min-h-8 items-center gap-2',
            row.kind === 'branch' &&
              'rounded-md bg-muted/[0.22] px-2 transition-colors hover:bg-muted/35'
          )}
        >
          {row.kind === 'end' ? (
            <span
              className='font-mono text-xs text-amber-700/65 dark:text-amber-300/65'
              aria-hidden
            >
              {marker}
            </span>
          ) : (
            <span
              className={cn(
                'relative z-10 flex size-5 shrink-0 items-center justify-center rounded-full border bg-background text-[11px] font-bold shadow-sm',
                isThen &&
                  'border-emerald-500/45 bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
                isElse &&
                  'border-rose-500/40 bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
                !isThen &&
                  !isElse &&
                  'border-teal-500/40 bg-teal-50 text-teal-700 dark:bg-teal-950 dark:text-teal-300'
              )}
              aria-hidden
            >
              {marker}
            </span>
          )}
          <span
            className={cn(
              'truncate text-[10px] font-bold tracking-[0.08em]',
              row.kind === 'end' &&
                'font-medium normal-case tracking-normal text-muted-foreground',
              isThen && 'text-emerald-800 dark:text-emerald-300',
              isElse && 'text-rose-800 dark:text-rose-300',
              row.kind === 'branch' &&
                !isThen &&
                !isElse &&
                'text-teal-800 dark:text-teal-300'
            )}
          >
            {tField(row.labelKey, row.labelValues)}
          </span>
          <span
            className={cn(
              'h-px min-w-4 flex-1',
              row.kind === 'end'
                ? 'border-t border-dashed border-amber-500/35'
                : isThen
                  ? 'bg-emerald-500/25'
                  : isElse
                    ? 'bg-rose-500/20'
                    : 'bg-teal-500/25'
            )}
          />
          {row.kind === 'branch' && (
            <span className='shrink-0 rounded-full border border-border/70 bg-background px-2 py-0.5 text-[9px] font-semibold tabular-nums text-muted-foreground shadow-sm'>
              {tField('stepCount', { count: row.count })}
            </span>
          )}
          {row.kind === 'branch' && onInsert && (
            <InsertStepPicker
              contentSide='bottom'
              contentAlign='end'
              sideOffset={4}
              onInsert={onInsert}
              trigger={
                <button
                  type='button'
                  className={cn(
                    'flex h-6 shrink-0 items-center gap-1 rounded-full border border-dashed border-muted-foreground/35 bg-background px-2 text-[10px] font-medium text-muted-foreground shadow-sm',
                    'transition-colors hover:border-primary/60 hover:bg-primary/5 hover:text-primary',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                  )}
                  aria-label={tField('addToThisBranch')}
                >
                  <Plus className='size-3' strokeWidth={2} />
                  <span className='max-sm:sr-only'>{addHereLabel}</span>
                </button>
              }
            />
          )}
          {row.kind === 'end' && conditional && (
            <span className='shrink-0 rounded-full bg-muted/70 px-2 py-0.5 text-[9px] font-medium text-muted-foreground'>
              {tField('continueLabel')}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function FlowEditorRow({
  campaignScenarios,
  sessionGateRuntimeContext,
  compact,
  coordinatePickTarget,
  dragHandle,
  enableDragDrop,
  handleLeafStepCardClick,
  index,
  insertChild,
  isDragging,
  nestedInDialog,
  availableVariables,
  variablePreviewValues,
  onCoordinatePickTargetChange,
  onRunStep,
  onSelectorPickTargetChange,
  onStopInlineRun,
  removeAt,
  removeChild,
  selectedIndex,
  selectorPickTarget,
  setSelectedIndex,
  step,
  stepCount,
  stepRunStates,
  toggleCoordPick,
  togglePick,
  updateAt
}: {
  campaignScenarios: RunScenarioCampaignOption[];
  sessionGateRuntimeContext?: SessionGateRuntimeContext;
  compact: boolean;
  coordinatePickTarget: CoordinatePickTarget | null;
  dragHandle: ReactNode;
  enableDragDrop: boolean;
  handleLeafStepCardClick: (index: number) => void;
  index: number;
  insertChild: (
    rootIndex: number,
    key: string,
    at: number,
    step: FlowStep
  ) => void;
  isDragging: boolean;
  nestedInDialog: boolean;
  availableVariables: string[];
  variablePreviewValues?: VariablePreviewValues;
  onCoordinatePickTargetChange?: (target: CoordinatePickTarget | null) => void;
  onRunStep?: (step: FlowStep, runKey: string) => void;
  onSelectorPickTargetChange?: (target: SelectorPickTarget | null) => void;
  onStopInlineRun?: () => void;
  removeAt: (index: number) => void;
  removeChild: (rootIndex: number, key: string, childIndex: number) => void;
  selectedIndex: number | null;
  selectorPickTarget: SelectorPickTarget | null;
  setSelectedIndex: Dispatch<SetStateAction<number | null>>;
  step: FlowStep;
  stepCount: number;
  stepRunStates: Record<string, 'idle' | 'running' | 'ok' | 'error'>;
  toggleCoordPick: (path: CoordinatePickTarget) => void;
  togglePick: (path: SelectorPickTarget) => void;
  updateAt: (index: number, step: FlowStep) => void;
}) {
  return (
    <div className={`flex items-stretch ${isDragging ? 'opacity-60' : ''}`}>
      {dragHandle}
      <FlowStepRail stepNumber={index + 1} showLine={index < stepCount - 1} />
      <div className='min-w-0 flex-1'>
        {isContainerType(step.type) ? (
          <BracketBlock
            step={step}
            stepIndex={index}
            rootStepIndex={index}
            pathFromRoot={[]}
            selected={selectedIndex === index}
            selectedChild={null}
            onSelectSelf={() =>
              setSelectedIndex(selectedIndex === index ? null : index)
            }
            onSelectChild={() => {}}
            onUpdate={(s) => updateAt(index, s)}
            onRemove={() => removeAt(index)}
            onRemoveChild={(key, ci) => removeChild(index, key, ci)}
            onInsertChild={(key, at, s) => insertChild(index, key, at, s)}
            compact={compact}
            nestedInDialog={nestedInDialog}
            selectorPickTarget={selectorPickTarget}
            onTogglePickSelector={
              onSelectorPickTargetChange ? togglePick : undefined
            }
            coordinatePickTarget={coordinatePickTarget}
            onToggleCoordinatePick={
              onCoordinatePickTargetChange ? toggleCoordPick : undefined
            }
            selfRunKey={encodeScenarioInlineRunKey(index, [])}
            stepRunStates={stepRunStates}
            onStopInlineRun={onStopInlineRun}
            onRunSelf={
              onRunStep
                ? () => onRunStep(step, encodeScenarioInlineRunKey(index, []))
                : undefined
            }
            onRunChild={onRunStep ? (s, k) => onRunStep(s, k) : undefined}
            campaignScenarios={campaignScenarios}
            availableVariables={availableVariables}
            variablePreviewValues={variablePreviewValues}
            sessionGateRuntimeContext={sessionGateRuntimeContext}
            enableDragDrop={enableDragDrop}
          />
        ) : (
          <StepCard
            step={step}
            index={index}
            selected={!compact && selectedIndex === index}
            compact={compact}
            onClick={() => handleLeafStepCardClick(index)}
            onRemove={() => removeAt(index)}
            onRun={
              onRunStep
                ? () => onRunStep(step, encodeScenarioInlineRunKey(index, []))
                : undefined
            }
            runState={stepRunStates[String(index)] ?? 'idle'}
            onStopInlineRun={onStopInlineRun}
            isPickTarget={
              selectorPickTarget != null &&
              selectorPickTarget.rootIndex === index &&
              (selectorPickTarget.path ?? []).length === 0
            }
            onTogglePickSelector={
              onSelectorPickTargetChange && isSelectorPickableStep(step)
                ? () => togglePick({ rootIndex: index, path: [] })
                : undefined
            }
            coordPickActive={
              coordinatePickTarget &&
              coordinatePickTargetEquals(coordinatePickTarget, {
                rootIndex: index,
                path: [],
                mode: 'tap_point'
              })
                ? 'tap_point'
                : coordinatePickTarget &&
                    coordinatePickTargetEquals(coordinatePickTarget, {
                      rootIndex: index,
                      path: [],
                      mode: 'swipe_segment'
                    })
                  ? 'swipe_segment'
                  : null
            }
            onTogglePickTapCoords={
              onCoordinatePickTargetChange && isTapCoordinatePickableStep(step)
                ? () =>
                    toggleCoordPick({
                      rootIndex: index,
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
                      rootIndex: index,
                      path: [],
                      mode: 'swipe_segment'
                    })
                : undefined
            }
            variablePreviewValues={variablePreviewValues}
          />
        )}
      </div>
    </div>
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
    // Variables the step writes (save_as, leased CANDIDATE_*, …) — without this
    // an OCR or resolver result is invisible to every step after it.
    variablesProducedByStep(step).forEach((name) => names.add(name));

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
