'use client';

import { Trash2, Play, Loader2, CheckCircle2, XCircle, Crosshair, MousePointerClick, Move, Square } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import { STEP_COLORS, getStepTypeName, getStepDisplay, getStepCategory } from './constants';
import { StepIcon } from './step-icon';

/** Build an <img> src from a stored image value (base64, object-storage URL, or local /captures/ path). */
function stepImageSrc(val: string): string {
  if (!val) return '';
  if (val.startsWith('http') || val.startsWith('/')) return val;
  return `data:image/jpeg;base64,${val}`;
}

/** Get the best available image for a tap step (element crop preferred, full screenshot as fallback). */
function getTapStepImage(step: FlowStep): string {
  const screen = step.screen as { element_image?: string; screenshot?: string } | undefined;
  const raw = screen?.element_image || screen?.screenshot || '';
  return raw ? stepImageSrc(raw) : '';
}

interface Props {
  step: FlowStep;
  index: number;
  selected: boolean;
  compact?: boolean;
  onClick: () => void;
  onRemove: () => void;
  /** Run this single step on the device. */
  onRun?: () => void;
  runState?: 'idle' | 'running' | 'ok' | 'error';
  /** Abort inline preview while this step is running. */
  onStopInlineRun?: () => void;
  /** True when this step is the current selector pick target. */
  isPickTarget?: boolean;
  /** When provided, shows a crosshair button to enter pick mode for this step. */
  onTogglePickSelector?: () => void;
  /** Coordinate pick from mirror (tap_ratio / tap fallback / swipe_ratio). */
  coordPickActive?: 'tap_point' | 'swipe_segment' | null;
  onTogglePickTapCoords?: () => void;
  onTogglePickSwipeCoords?: () => void;
}

export function StepCard({
  step,
  selected,
  compact = false,
  onClick,
  onRemove,
  onRun,
  runState = 'idle',
  onStopInlineRun,
  isPickTarget,
  onTogglePickSelector,
  coordPickActive,
  onTogglePickTapCoords,
  onTogglePickSwipeCoords,
}: Props) {
  const tFlow = useTranslations('campaignsFeature.flowBracket');
  const colorCls = STEP_COLORS[step.type] ?? 'border-l-gray-400';
  const typeName = getStepTypeName(step.type);
  const { target, selectorBadge } = getStepDisplay(step);
  const category = getStepCategory(step.type);

  // User-defined title/description override auto-generated display
  const title = (step.title as string | undefined)?.trim() || undefined;
  const description = (step.description as string | undefined)?.trim() || undefined;
  const runScenarioRef =
    step.type === 'run_scenario'
      ? String((step as any).scenario_name || (step as any).scenario_id || '').trim()
      : '';
  const runScenarioEmptyHint =
    step.type === 'run_scenario' && !title && !runScenarioRef ? tFlow('runScenario.cardPickHint') : '';
  const secondRowMain = title || target || runScenarioEmptyHint;

  return (
    <div
      className={cn(
        'group rounded-md border-l-[3px] border bg-card transition-all cursor-pointer',
        colorCls,
        selected && 'ring-2 ring-primary/40 bg-accent/30',
        isPickTarget && 'ring-2 ring-amber-500/80 shadow-[0_0_0_1px_rgba(245,158,11,0.35)]',
        coordPickActive && 'ring-2 ring-sky-500/75 shadow-[0_0_0_1px_rgba(14,165,233,0.35)]',
      )}
      onClick={onClick}
    >
      {isPickTarget && (
        <div className='flex items-center gap-1.5 border-b border-amber-400/30 bg-amber-50/80 px-2.5 py-1 dark:bg-amber-950/20'>
          <Crosshair size={10} className='shrink-0 text-amber-600' />
          <span className='text-[10px] text-amber-800 dark:text-amber-300'>
            Chạm mirror hoặc chọn dòng trong cây UI phía trên để gán
          </span>
        </div>
      )}
      {coordPickActive === 'tap_point' && (
        <div className='flex items-center gap-1.5 border-b border-sky-400/40 bg-sky-50/90 px-2.5 py-1 dark:bg-sky-950/25'>
          <MousePointerClick size={10} className='shrink-0 text-sky-700 dark:text-sky-400' />
          <span className='text-[10px] text-sky-900 dark:text-sky-200'>
            Chạm một điểm trên mirror để lấy tọa độ (0–1)
          </span>
        </div>
      )}
      {coordPickActive === 'swipe_segment' && (
        <div className='flex items-center gap-1.5 border-b border-sky-400/40 bg-sky-50/90 px-2.5 py-1 dark:bg-sky-950/25'>
          <Move size={10} className='shrink-0 text-sky-700 dark:text-sky-400' />
          <span className='text-[10px] text-sky-900 dark:text-sky-200'>
            Vuốt trên mirror để lấy đoạn (điểm đầu → cuối)
          </span>
        </div>
      )}
      <div className='flex items-center gap-2 px-2.5 py-1.5 hover:bg-accent/50'>
        {/* Run state indicator */}
        {runState === 'running' && <Loader2 size={11} className='shrink-0 animate-spin text-primary' />}
        {runState === 'ok' && <CheckCircle2 size={11} className='shrink-0 text-emerald-500' />}
        {runState === 'error' && <XCircle size={11} className='shrink-0 text-red-500' />}
        {runState === 'idle' && <StepIcon type={step.type} size={12} className='shrink-0' />}

        <div className='min-w-0 flex-1 overflow-hidden'>
          {/* Row 1: type name + category badge */}
          <div className='flex items-center gap-1.5'>
            <span
              className={cn(
                'text-[10px] leading-tight text-muted-foreground',
                step.type === 'run_scenario'
                  ? 'font-semibold tracking-tight normal-case'
                  : 'font-bold uppercase tracking-wide',
              )}
            >
              {typeName}
            </span>
            <span className={cn(
              'rounded px-1 py-px text-[8px] font-bold uppercase tracking-wide',
              category === 'flow'
                ? 'bg-purple-500/15 text-purple-600 dark:text-purple-400'
                : 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
            )}>
              {category === 'flow' ? 'Luồng' : 'HĐ'}
            </span>
          </div>

          {/* Row 2: title (user-defined) OR auto target + selector badge */}
          {secondRowMain && (
            <div className='mt-0.5 flex items-center gap-1 overflow-hidden'>
              {!title && selectorBadge && (
                <span className='flex-shrink-0 rounded bg-muted px-1 py-px font-mono text-[9px] text-muted-foreground'>
                  {selectorBadge}
                </span>
              )}
              <span
                className={cn(
                  'truncate text-[12px] font-medium leading-tight',
                  title ? 'text-foreground' : runScenarioEmptyHint ? 'text-muted-foreground' : 'text-foreground/80',
                )}
                title={title || target || runScenarioEmptyHint}
              >
                {title || target || runScenarioEmptyHint}
              </span>
            </div>
          )}

          {/* Row 3: description */}
          {description && (
            <span className='block truncate text-[10px] italic text-muted-foreground'>
              {description}
            </span>
          )}
        </div>

        {(() => { const imgSrc = step.type === 'tap' ? getTapStepImage(step) : ''; return imgSrc ? (
          <img src={imgSrc} alt="" className='h-12 w-8 shrink-0 rounded object-cover object-top border border-border/40' />
        ) : null; })()}

        {onTogglePickTapCoords && (
          <button
            type='button'
            className={cn(
              'shrink-0 rounded p-0.5 transition-all',
              coordPickActive === 'tap_point'
                ? 'text-sky-800 bg-sky-500/25 dark:text-sky-300'
                : 'opacity-0 group-hover:opacity-100 hover:bg-sky-500/15 hover:text-sky-800 dark:hover:text-sky-300',
            )}
            onClick={(e) => { e.stopPropagation(); onTogglePickTapCoords(); }}
            aria-label='Lấy tọa độ chạm trên mirror'
            title='Chạm trên mirror để điền tọa độ'
          >
            <MousePointerClick size={11} />
          </button>
        )}
        {onTogglePickSwipeCoords && (
          <button
            type='button'
            className={cn(
              'shrink-0 rounded p-0.5 transition-all',
              coordPickActive === 'swipe_segment'
                ? 'text-sky-800 bg-sky-500/25 dark:text-sky-300'
                : 'opacity-0 group-hover:opacity-100 hover:bg-sky-500/15 hover:text-sky-800 dark:hover:text-sky-300',
            )}
            onClick={(e) => { e.stopPropagation(); onTogglePickSwipeCoords(); }}
            aria-label='Lấy tọa độ vuốt trên mirror'
            title='Vuốt trên mirror để điền đoạn vuốt'
          >
            <Move size={11} />
          </button>
        )}
        {onTogglePickSelector && (
          <button
            type='button'
            className={cn(
              'shrink-0 rounded p-0.5 transition-all',
              isPickTarget
                ? 'text-amber-700 bg-amber-500/20 dark:text-amber-300'
                : 'opacity-0 group-hover:opacity-100 hover:bg-amber-500/15 hover:text-amber-700',
            )}
            onClick={(e) => { e.stopPropagation(); onTogglePickSelector(); }}
            aria-label='Chọn selector từ màn hình'
            title='Chọn selector từ mirror / cây UI'
          >
            <Crosshair size={11} />
          </button>
        )}
        {onRun && runState !== 'running' && (
          <button
            type='button'
            className={cn(
              'shrink-0 rounded p-0.5 transition-opacity hover:bg-primary/10 hover:text-primary',
              compact ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
            )}
            onClick={(e) => { e.stopPropagation(); onRun(); }}
            aria-label='Chạy bước này'
            title='Chạy bước này trên thiết bị'
          >
            <Play size={11} />
          </button>
        )}
        {onStopInlineRun && runState === 'running' && (
          <button
            type='button'
            className='shrink-0 rounded p-0.5 hover:bg-destructive/15 hover:text-destructive'
            onClick={(e) => { e.stopPropagation(); onStopInlineRun(); }}
            aria-label='Dừng chạy thử'
            title='Dừng chạy thử'
          >
            <Square size={11} fill='currentColor' />
          </button>
        )}
        <button
          type='button'
          className='shrink-0 rounded p-0.5 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100'
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          aria-label='Xóa bước'
        >
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  );
}
