'use client';

import { useCallback, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { ChevronDown, ChevronRight, Crosshair, Loader2, Play, Square, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { isContainerType, type FlowStep } from '../scenario-steps/types';
import { BRACKET_COLORS, getStepTypeName, getStepSummary } from './constants';
import { StepIcon } from './step-icon';
import { StepCard } from './step-card';
import { InsertGap } from './insert-button';
import { StepDetailPanel } from './step-detail-panel';
import { StepEditOverlay } from './step-edit-overlay';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  RepeatFields,
  RepeatUntilFields,
  IfElementFields,
  IfVariableFields,
  LoopFields,
} from '../scenario-steps/control-flow-editors';
import type { SelectorPickTarget } from './selector-pick';
import { selectorPickTargetEquals, isSelectorPickableStep } from './selector-pick';
import type { CoordinatePickTarget } from './coordinate-pick';
import {
  coordinatePickTargetEquals,
  isTapCoordinatePickableStep,
  isSwipeCoordinatePickableStep,
} from './coordinate-pick';
import { encodeFlowListRef, stableStepDnDId } from './flow-dnd-ids';
import { SortableFlowRow } from './sortable-flow-row';
import { encodeScenarioInlineRunKey } from './inline-run-key';
import type { RunScenarioCampaignOption } from '../scenario-steps/run-scenario-editor';

// ── Step mutation helpers ────────────────────────────────────────────────────

function removeFromStep(step: FlowStep, key: string, ci: number): FlowStep {
  const next = { ...step } as any;
  if (key.startsWith('branches.')) {
    const bi = parseInt(key.split('.')[1] ?? '0');
    const branches = [...(next.branches ?? [])];
    branches[bi] = { ...branches[bi], steps: branches[bi].steps.filter((_: any, i: number) => i !== ci) };
    next.branches = branches;
  } else {
    next[key] = (next[key] ?? []).filter((_: any, i: number) => i !== ci);
  }
  return next as FlowStep;
}

function insertIntoStep(step: FlowStep, key: string, at: number, newStep: FlowStep): FlowStep {
  const next = { ...step } as any;
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
  return next as FlowStep;
}

function updateChildInStep(step: FlowStep, key: string, ci: number, newChild: FlowStep): FlowStep {
  const next = { ...step } as any;
  if (key.startsWith('branches.')) {
    const bi = parseInt(key.split('.')[1] ?? '0');
    const branches = [...(next.branches ?? [])];
    const bSteps = [...(branches[bi].steps ?? [])];
    bSteps[ci] = newChild;
    branches[bi] = { ...branches[bi], steps: bSteps };
    next.branches = branches;
  } else {
    const arr = [...(next[key] ?? [])];
    arr[ci] = newChild;
    next[key] = arr;
  }
  return next as FlowStep;
}

// ── Props ────────────────────────────────────────────────────────────────────

interface BracketBlockProps {
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
  /** See FlowEditor — must match when this block is inside a parent Radix Dialog. */
  nestedInDialog?: boolean;
  selectorPickTarget?: SelectorPickTarget | null;
  onTogglePickSelector?: (path: SelectorPickTarget) => void;
  coordinatePickTarget?: CoordinatePickTarget | null;
  onToggleCoordinatePick?: (path: CoordinatePickTarget) => void;
  /** Nesting depth — used for visual indentation cues. */
  depth?: number;
  /** Run a child step or nested block on the device inline (`runKey` for UI state). */
  onRunChild?: (step: FlowStep, runKey: string) => void;
  /** Run the entire control-flow block (loop / if / repeat) on the device. */
  onRunSelf?: () => void;
  /** Key for `stepRunStates` — this bracket’s header. */
  selfRunKey?: string;
  stepRunStates?: Record<string, 'idle' | 'running' | 'ok' | 'error'>;
  /** Abort the current inline preview (same as global stop). */
  onStopInlineRun?: () => void;
  /**
   * The index of this block in the ROOT steps array (not local).
   * Needed for correct SelectorPickTarget when blocks are nested.
   * Defaults to stepIndex (correct for root-level blocks).
   */
  rootStepIndex?: number;
  /**
   * Path from the root step to this block's position.
   * Each segment: { listKey, childIndex } traversed to reach this block.
   * Empty array (default) = this IS a root step.
   */
  pathFromRoot?: Array<{ listKey: string; childIndex: number }>;
  campaignScenarios?: RunScenarioCampaignOption[];
}

// ── ChildStepList ────────────────────────────────────────────────────────────

function SectionLabel({ label, color, variant }: { label: string; color: string; variant?: 'then' | 'else' }) {
  return (
    <div className={cn(
      'my-1 flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-bold',
      variant === 'then' && 'bg-green-500/10 text-green-700 dark:text-green-400',
      variant === 'else' && 'bg-red-500/10 text-red-600 dark:text-red-400',
      !variant && cn('text-[9px] uppercase tracking-widest', color),
    )}>
      {variant === 'then' && <span>✓</span>}
      {variant === 'else' && <span>✗</span>}
      {label}
    </div>
  );
}

interface ChildStepListProps {
  steps: FlowStep[];
  listKey: string;
  selectedChild: number | null;
  startIndex: number;
  parentStepIndex: number;
  onSelectChild: (flatIndex: number) => void;
  onRemoveChild: (key: string, childIndex: number) => void;
  onInsertChild: (key: string, insertAt: number, newStep: FlowStep) => void;
  onUpdateChild: (key: string, childIndex: number, newStep: FlowStep) => void;
  compact?: boolean;
  selectorPickTarget?: SelectorPickTarget | null;
  onTogglePickSelector?: (path: SelectorPickTarget) => void;
  coordinatePickTarget?: CoordinatePickTarget | null;
  onToggleCoordinatePick?: (path: CoordinatePickTarget) => void;
  depth?: number;
  onEditChild?: (listKey: string, ci: number) => void;
  onRunChild?: (step: FlowStep, runKey: string) => void;
  rootStepIndex?: number;
  pathFromRoot?: Array<{ listKey: string; childIndex: number }>;
  nestedInDialog?: boolean;
  stepRunStates?: Record<string, 'idle' | 'running' | 'ok' | 'error'>;
  onStopInlineRun?: () => void;
  campaignScenarios?: RunScenarioCampaignOption[];
}

function ChildStepList({
  steps,
  listKey,
  selectedChild,
  startIndex,
  parentStepIndex,
  onSelectChild,
  onRemoveChild,
  onInsertChild,
  onUpdateChild,
  compact,
  selectorPickTarget,
  onTogglePickSelector,
  coordinatePickTarget,
  onToggleCoordinatePick,
  depth = 0,
  onEditChild,
  onRunChild,
  rootStepIndex,
  pathFromRoot,
  nestedInDialog,
  stepRunStates = {},
  onStopInlineRun,
  campaignScenarios = [],
}: ChildStepListProps) {
  const tBracket = useTranslations('campaignsFeature.flowBracket');
  const pathKey = JSON.stringify(pathFromRoot ?? []);
  const sortableContainerId = useMemo(() => {
    const path = (JSON.parse(pathKey) || []) as Array<{ listKey: string; childIndex: number }>;
    return encodeFlowListRef({
      kind: 'nested',
      rootIndex: rootStepIndex ?? parentStepIndex,
      pathToBracket: path,
      listKey,
    });
  }, [rootStepIndex, parentStepIndex, listKey, pathKey]);

  const childIds = useMemo(() => steps.map((s, i) => stableStepDnDId(s, i)), [steps]);

  return (
    <div className='space-y-0'>
      <SortableContext
        id={sortableContainerId}
        items={childIds}
        strategy={verticalListSortingStrategy}
      >
        {steps.map((child, ci) => {
          const rowId = childIds[ci]!;
        if (isContainerType(child.type)) {
          const nestedPath = [...(pathFromRoot ?? []), { listKey, childIndex: ci }];
          const bracketRunKey = encodeScenarioInlineRunKey(rootStepIndex ?? parentStepIndex, nestedPath);
          return (
            <div key={rowId}>
              <InsertGap onInsert={(s) => onInsertChild(listKey, ci, s)} />
              <SortableFlowRow id={rowId}>
                {(dragHandle, isDragging) => (
                  <div className={`flex items-stretch ${isDragging ? 'opacity-60' : ''}`}>
                    {dragHandle}
                    <div className='min-w-0 flex-1'>
                      <BracketBlock
                        step={child}
                        stepIndex={ci}
                        rootStepIndex={rootStepIndex}
                        pathFromRoot={nestedPath}
                        selected={false}
                        selectedChild={null}
                        onSelectSelf={() => {
                          if (onEditChild) {
                            onEditChild(listKey, ci);
                            return;
                          }
                          onSelectChild(startIndex + ci);
                        }}
                        onSelectChild={() => {}}
                        onUpdate={(newChild) => onUpdateChild(listKey, ci, newChild)}
                        onRemove={() => onRemoveChild(listKey, ci)}
                        onRemoveChild={(nestedKey, nci) =>
                          onUpdateChild(listKey, ci, removeFromStep(child, nestedKey, nci))
                        }
                        onInsertChild={(nestedKey, at, newStep) =>
                          onUpdateChild(listKey, ci, insertIntoStep(child, nestedKey, at, newStep))
                        }
                        compact={compact}
                        nestedInDialog={nestedInDialog}
                        selectorPickTarget={selectorPickTarget}
                        onTogglePickSelector={onTogglePickSelector}
                        coordinatePickTarget={coordinatePickTarget}
                        onToggleCoordinatePick={onToggleCoordinatePick}
                        depth={depth + 1}
                        onRunChild={onRunChild}
                        selfRunKey={bracketRunKey}
                        stepRunStates={stepRunStates}
                        onStopInlineRun={onStopInlineRun}
                        onRunSelf={onRunChild ? () => onRunChild(child, bracketRunKey) : undefined}
                        campaignScenarios={campaignScenarios}
                      />
                    </div>
                  </div>
                )}
              </SortableFlowRow>
            </div>
          );
        }

        const leafPath = [...(pathFromRoot ?? []), { listKey, childIndex: ci }];
        const leafRunKey = encodeScenarioInlineRunKey(rootStepIndex ?? parentStepIndex, leafPath);
        const childPickPath: SelectorPickTarget = {
          rootIndex: rootStepIndex ?? parentStepIndex,
          path: leafPath,
        };
        const isPickTarget = selectorPickTarget != null && selectorPickTargetEquals(selectorPickTarget, childPickPath);
        const childTapCoord: CoordinatePickTarget = {
          rootIndex: rootStepIndex ?? parentStepIndex,
          path: [...(pathFromRoot ?? []), { listKey, childIndex: ci }],
          mode: 'tap_point',
        };
        const childSwipeCoord: CoordinatePickTarget = {
          ...childTapCoord,
          mode: 'swipe_segment',
        };
        const coordPickActive =
          coordinatePickTarget && coordinatePickTargetEquals(coordinatePickTarget, childTapCoord)
            ? ('tap_point' as const)
            : coordinatePickTarget && coordinatePickTargetEquals(coordinatePickTarget, childSwipeCoord)
              ? ('swipe_segment' as const)
              : null;
        return (
          <div key={rowId}>
            <InsertGap onInsert={(s) => onInsertChild(listKey, ci, s)} />
            <SortableFlowRow id={rowId}>
              {(dragHandle, isDragging) => (
                <div className={`flex items-stretch ${isDragging ? 'opacity-60' : ''}`}>
                  {dragHandle}
                  <div className='min-w-0 flex-1'>
                    <StepCard
                      step={child}
                      index={startIndex + ci}
                      selected={selectedChild === startIndex + ci}
                      onClick={() => onEditChild ? onEditChild(listKey, ci) : onSelectChild(startIndex + ci)}
                      onRemove={() => onRemoveChild(listKey, ci)}
                      onRun={onRunChild ? () => onRunChild(child, leafRunKey) : undefined}
                      runState={stepRunStates[leafRunKey] ?? 'idle'}
                      onStopInlineRun={onStopInlineRun}
                      isPickTarget={isPickTarget}
                      onTogglePickSelector={
                        onTogglePickSelector && isSelectorPickableStep(child)
                          ? () => onTogglePickSelector(childPickPath)
                          : undefined
                      }
                      coordPickActive={coordPickActive}
                      onTogglePickTapCoords={
                        onToggleCoordinatePick && isTapCoordinatePickableStep(child)
                          ? () => onToggleCoordinatePick(childTapCoord)
                          : undefined
                      }
                      onTogglePickSwipeCoords={
                        onToggleCoordinatePick && isSwipeCoordinatePickableStep(child)
                          ? () => onToggleCoordinatePick(childSwipeCoord)
                          : undefined
                      }
                    />
                  </div>
                </div>
              )}
            </SortableFlowRow>
          </div>
        );
      })}
        <InsertGap onInsert={(s) => onInsertChild(listKey, steps.length, s)} />
      </SortableContext>
      {steps.length === 0 && (
        <div className='rounded-md border border-dashed border-muted-foreground/25 bg-muted/20 px-2 py-2 text-center'>
          <p className='text-[11px] font-medium text-muted-foreground'>{tBracket('emptyBranchTitle')}</p>
          <p className='mt-0.5 text-[10px] leading-snug text-muted-foreground/90'>{tBracket('emptyBranchBody')}</p>
        </div>
      )}
    </div>
  );
}

// ── BracketBlock ─────────────────────────────────────────────────────────────

function getChildStep(step: FlowStep, listKey: string, ci: number): FlowStep | null {
  if (listKey.startsWith('branches.')) {
    const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
    return (step.branches as any[])?.[bi]?.steps?.[ci] ?? null;
  }
  return ((step as any)[listKey] as FlowStep[])?.[ci] ?? null;
}

export function BracketBlock({
  step, stepIndex, selected, selectedChild,
  onSelectSelf, onSelectChild, onUpdate, onRemove, onRemoveChild, onInsertChild,
  compact = false,
  nestedInDialog = false,
  selectorPickTarget,
  onTogglePickSelector,
  coordinatePickTarget,
  onToggleCoordinatePick,
  depth = 0,
  onRunChild,
  onRunSelf,
  selfRunKey,
  stepRunStates = {},
  onStopInlineRun,
  rootStepIndex,
  pathFromRoot,
  campaignScenarios = [],
}: BracketBlockProps) {
  const tFlow = useTranslations('campaignsFeature.flowBracket');
  const [collapsed, setCollapsed] = useState(false);
  const [editingChildPath, setEditingChildPath] = useState<{ listKey: string; ci: number } | null>(null);
  const editingChild = editingChildPath ? getChildStep(step, editingChildPath.listKey, editingChildPath.ci) : null;
  const colors = BRACKET_COLORS[step.type] ?? BRACKET_COLORS.repeat;
  const blockTitle = useMemo(() => {
    switch (step.type) {
      case 'loop':
        return tFlow('blockTitle.loop');
      case 'repeat':
        return tFlow('blockTitle.repeat');
      case 'repeat_until':
        return tFlow('blockTitle.repeat_until');
      case 'if_element':
        return tFlow('blockTitle.if_element');
      case 'if_variable':
        return tFlow('blockTitle.if_variable');
      case 'if':
        return tFlow('blockTitle.if');
      case 'random_pick':
        return tFlow('blockTitle.random_pick');
      case 'run_scenario':
        return tFlow('blockTitle.run_scenario');
      default:
        return getStepTypeName(step.type);
    }
  }, [step.type, tFlow]);
  const summary = useMemo(() => {
    if (step.type === 'random_pick') {
      return tFlow('branchSummary', { count: step.branches?.length ?? 0 });
    }
    return getStepSummary(step);
  }, [step, tFlow]);

  // Effective root info — for nested blocks, rootStepIndex differs from stepIndex
  const effectiveRootIndex = rootStepIndex ?? stepIndex;
  const effectivePath = pathFromRoot ?? [];

  // Pick target pointing to THIS block's step (for if_element condition picking)
  const selfPickPath: SelectorPickTarget = { rootIndex: effectiveRootIndex, path: effectivePath };
  const pickingCondition =
    step.type === 'if_element' &&
    selectorPickTarget &&
    selectorPickTargetEquals(selectorPickTarget, selfPickPath);

  // Update a child step within one of this bracket's arrays
  const handleUpdateChild = useCallback(
    (key: string, ci: number, newChild: FlowStep) => {
      onUpdate(updateChildInStep(step, key, ci, newChild));
    },
    [step, onUpdate],
  );

  const selfRunState = selfRunKey ? (stepRunStates[selfRunKey] ?? 'idle') : 'idle';

  const childListProps = {
    selectedChild,
    startIndex: 0,
    parentStepIndex: stepIndex,
    onSelectChild,
    onRemoveChild,
    onInsertChild,
    onUpdateChild: handleUpdateChild,
    compact,
    selectorPickTarget,
    onTogglePickSelector,
    coordinatePickTarget,
    onToggleCoordinatePick,
    depth,
    onEditChild: (lk: string, ci: number) => setEditingChildPath({ listKey: lk, ci }),
    onRunChild,
    rootStepIndex: effectiveRootIndex,
    pathFromRoot: effectivePath,
    nestedInDialog,
    stepRunStates,
    onStopInlineRun,
    campaignScenarios,
  };

  return (
    <>
    {nestedInDialog && !compact && editingChild != null && editingChildPath && editingChild && (
      <StepEditOverlay onClose={() => setEditingChildPath(null)}>
        <StepDetailPanel
          step={editingChild}
          onChange={(s) => onUpdate(updateChildInStep(step, editingChildPath.listKey, editingChildPath.ci, s))}
          onClose={() => setEditingChildPath(null)}
          campaignScenarios={campaignScenarios}
          onRequestPickSelector={onTogglePickSelector ? () => {
            const path: SelectorPickTarget = {
              rootIndex: effectiveRootIndex,
              path: [...effectivePath, { listKey: editingChildPath.listKey, childIndex: editingChildPath.ci }],
            };
            setEditingChildPath(null);
            onTogglePickSelector(path);
          } : undefined}
          onRequestPickTapCoords={
            onToggleCoordinatePick &&
            editingChildPath &&
            (editingChild.type === 'tap_ratio' || editingChild.type === 'tap')
              ? () => {
                  const path = [
                    ...effectivePath,
                    { listKey: editingChildPath.listKey, childIndex: editingChildPath.ci },
                  ];
                  setEditingChildPath(null);
                  onToggleCoordinatePick({ rootIndex: effectiveRootIndex, path, mode: 'tap_point' });
                }
              : undefined
          }
          onRequestPickSwipeCoords={
            onToggleCoordinatePick && editingChildPath && editingChild.type === 'swipe_ratio'
              ? () => {
                  const path = [
                    ...effectivePath,
                    { listKey: editingChildPath.listKey, childIndex: editingChildPath.ci },
                  ];
                  setEditingChildPath(null);
                  onToggleCoordinatePick({ rootIndex: effectiveRootIndex, path, mode: 'swipe_segment' });
                }
              : undefined
          }
        />
      </StepEditOverlay>
    )}

    {!nestedInDialog && !compact && (
    <Dialog
      open={editingChild != null}
      onOpenChange={(open) => { if (!open) setEditingChildPath(null); }}
    >
      <DialogContent className='max-w-sm p-0 gap-0'>
        <DialogHeader className='sr-only'>
          <DialogTitle>Chỉnh sửa bước</DialogTitle>
        </DialogHeader>
        {editingChild && editingChildPath && (
          <StepDetailPanel
            step={editingChild}
            onChange={(s) => onUpdate(updateChildInStep(step, editingChildPath.listKey, editingChildPath.ci, s))}
            onClose={() => setEditingChildPath(null)}
            campaignScenarios={campaignScenarios}
            onRequestPickSelector={onTogglePickSelector ? () => {
              const path: SelectorPickTarget = {
                rootIndex: effectiveRootIndex,
                path: [...effectivePath, { listKey: editingChildPath.listKey, childIndex: editingChildPath.ci }],
              };
              setEditingChildPath(null);
              onTogglePickSelector(path);
            } : undefined}
            onRequestPickTapCoords={
              onToggleCoordinatePick &&
              editingChildPath &&
              (editingChild.type === 'tap_ratio' || editingChild.type === 'tap')
                ? () => {
                    const path = [
                      ...effectivePath,
                      { listKey: editingChildPath.listKey, childIndex: editingChildPath.ci },
                    ];
                    setEditingChildPath(null);
                    onToggleCoordinatePick({ rootIndex: effectiveRootIndex, path, mode: 'tap_point' });
                  }
                : undefined
            }
            onRequestPickSwipeCoords={
              onToggleCoordinatePick && editingChildPath && editingChild.type === 'swipe_ratio'
                ? () => {
                    const path = [
                      ...effectivePath,
                      { listKey: editingChildPath.listKey, childIndex: editingChildPath.ci },
                    ];
                    setEditingChildPath(null);
                    onToggleCoordinatePick({ rootIndex: effectiveRootIndex, path, mode: 'swipe_segment' });
                  }
                : undefined
            }
          />
        )}
      </DialogContent>
    </Dialog>
    )}
    <div
      className={cn(
        'rounded-md overflow-hidden',
        // Thicker border for top-level, thinner for nested
        depth === 0 ? 'border-2' : 'border',
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
        <span className={cn('text-xs font-semibold tracking-tight normal-case', colors.label)}>{blockTitle}</span>
        <span className='min-w-0 flex-1 truncate text-[10px] text-muted-foreground'>{summary}</span>

        {/* Nesting depth badge — helps user track where they are */}
        {depth > 0 && (
          <span className={cn('shrink-0 rounded px-1 py-px text-[8px] font-bold opacity-60', colors.label)}>
            L{depth + 1}
          </span>
        )}

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
              onTogglePickSelector(selfPickPath);
            }}
          >
            <Crosshair size={12} strokeWidth={2} />
          </button>
        )}
        {selfRunState === 'running' && (
          <Loader2 size={12} className='shrink-0 animate-spin text-primary' aria-hidden />
        )}
        {selfRunState === 'ok' && (
          <span className='text-[10px] font-bold text-emerald-600' title='Xong'>✓</span>
        )}
        {selfRunState === 'error' && (
          <span className='text-[10px] font-bold text-red-600' title='Lỗi'>✕</span>
        )}
        {onRunSelf && selfRunState !== 'running' && (
          <button
            type='button'
            className='shrink-0 rounded p-0.5 hover:bg-green-500/15 hover:text-green-600'
            title='Chạy khối này trên thiết bị'
            onClick={(e) => { e.stopPropagation(); onRunSelf(); }}
          >
            <Play size={10} strokeWidth={2} />
          </button>
        )}
        {onStopInlineRun && selfRunState === 'running' && (
          <button
            type='button'
            className='shrink-0 rounded p-0.5 hover:bg-destructive/15 hover:text-destructive'
            title='Dừng chạy thử'
            onClick={(e) => { e.stopPropagation(); onStopInlineRun(); }}
          >
            <Square size={10} strokeWidth={2} fill='currentColor' />
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
          {step.type === 'loop' && (
            <LoopFields step={step} onChange={(f, v) => onUpdate({ ...step, [f]: v })} />
          )}
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
        <div className={cn('pb-1', depth === 0 ? 'px-2' : 'px-1.5')}>
          {(step.type === 'loop' || step.type === 'repeat' || step.type === 'repeat_until') && (
            <ChildStepList
              steps={step.steps ?? []}
              listKey='steps'
              {...childListProps}
            />
          )}

          {(step.type === 'if_element' || step.type === 'if_variable' || step.type === 'if') && (() => {
            const thenSteps = step.then ?? [];
            const elseSteps = step.else ?? [];
            return (
              <>
                <SectionLabel label='Nếu đúng — thực hiện' color={colors.label} variant='then' />
                <ChildStepList steps={thenSteps} listKey='then' {...childListProps} />
                <SectionLabel label='Nếu sai — thực hiện' color={colors.label} variant='else' />
                <ChildStepList steps={elseSteps} listKey='else' {...childListProps} />
              </>
            );
          })()}

          {step.type === 'random_pick' && (
            <div className='space-y-2 pt-0.5'>
              <p className='rounded-md bg-muted/40 px-2 py-1.5 text-[10px] leading-relaxed text-muted-foreground'>
                {tFlow('randomPick.explainer')}
              </p>
              {(step.branches ?? []).map((branch: any, bi: number) => (
                <div
                  key={bi}
                  className='space-y-1.5 rounded-md border border-dashed border-border/80 bg-background/40 p-2'
                >
                  <div className='flex flex-wrap items-baseline gap-x-2 gap-y-0.5'>
                    <span className={cn('text-xs font-semibold', colors.label)}>
                      {tFlow('randomPick.branchHeading', { letter: String.fromCharCode(65 + bi) })}
                    </span>
                    <span className='text-[10px] text-muted-foreground'>
                      {tFlow('randomPick.weightLine', { weight: branch.weight ?? 1 })}
                    </span>
                  </div>
                  <ChildStepList
                    steps={branch.steps ?? []}
                    listKey={`branches.${bi}.steps`}
                    {...childListProps}
                  />
                </div>
              ))}
            </div>
          )}

          {step.type === 'run_scenario' && (
            <p className='py-1 text-[10px] text-muted-foreground'>
              {step.scenario_name || step.scenario_id ? (
                <>
                  {tFlow('runScenario.inlineCalls', {
                    ref: String(step.scenario_name || step.scenario_id),
                  })}
                </>
              ) : (
                tFlow('runScenario.inlineNotSet')
              )}
            </p>
          )}
        </div>
      )}

      {/* End bar */}
      {!collapsed && (
        <div
          className={cn(
            'flex items-center gap-1.5 border-t px-2 py-1 text-[10px] font-medium normal-case opacity-80',
            colors.bg,
            colors.label,
          )}
        >
          <span className='font-mono text-muted-foreground' aria-hidden>
            └
          </span>
          <span>{tFlow('endBlock', { title: blockTitle })}</span>
        </div>
      )}
    </div>
    </>
  );
}
