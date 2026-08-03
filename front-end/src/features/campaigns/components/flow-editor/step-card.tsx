'use client';

import {
  Trash2,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Crosshair,
  MousePointerClick,
  Move,
  Square
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import {
  STEP_COLORS,
  formatStepLabelForCard,
  getStepCategory
} from './constants';
import { useCampaignFlowI18n } from './flow-i18n';
import { StepIcon } from './step-icon';

/** Build an <img> src from a stored image value (base64, object-storage URL, or local /captures/ path). */
function stepImageSrc(val: string): string {
  if (!val) return '';
  if (val.startsWith('http') || val.startsWith('/')) return val;
  return `data:image/jpeg;base64,${val}`;
}

/** Get the full-screen image for a tap step (element crops are not persisted). */
function getTapStepImage(step: FlowStep): string {
  const screen = step.screen as
    | { element_image?: string; screenshot?: string }
    | undefined;
  const raw = screen?.screenshot || '';
  return raw ? stepImageSrc(raw) : '';
}

interface Props {
  step: FlowStep;
  index: number;
  selected: boolean;
  compact?: boolean;
  onClick: () => void;
  onRemove: () => void;
  onRun?: () => void;
  runState?: 'idle' | 'running' | 'ok' | 'error';
  onStopInlineRun?: () => void;
  isPickTarget?: boolean;
  onTogglePickSelector?: () => void;
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
  onTogglePickSwipeCoords
}: Props) {
  const tFlow = useTranslations('campaignsFeature.flowBracket');
  const { getStepTypeName, getStepDisplay } = useCampaignFlowI18n();
  const colorCls = STEP_COLORS[step.type] ?? 'border-l-gray-400';
  const typeName = formatStepLabelForCard(getStepTypeName(step.type));
  const { target, selectorBadge } = getStepDisplay(step);
  const category = getStepCategory(step.type);

  const title = (step.title as string | undefined)?.trim() || undefined;
  const description =
    (step.description as string | undefined)?.trim() || undefined;
  const runScenarioRef =
    step.type === 'run_scenario'
      ? String(
          (step as any).scenario_name || (step as any).scenario_id || ''
        ).trim()
      : '';
  const runScenarioEmptyHint =
    step.type === 'run_scenario' && !title && !runScenarioRef
      ? tFlow('runScenario.cardPickHint')
      : '';
  const secondRowMain = title || target || runScenarioEmptyHint;

  const categoryLabel =
    category === 'flow' ? tFlow('categoryFlow') : tFlow('categoryAction');

  return (
    <div
      className={cn(
        'group cursor-pointer rounded-lg border border-l-[3px] border-border/70 bg-card shadow-sm transition-[background-color,border-color,box-shadow]',
        colorCls,
        selected && 'bg-accent/25 ring-2 ring-primary/35',
        isPickTarget &&
          'shadow-[0_0_0_1px_rgba(245,158,11,0.35)] ring-2 ring-amber-500/80',
        coordPickActive &&
          'shadow-[0_0_0_1px_rgba(14,165,233,0.35)] ring-2 ring-sky-500/75'
      )}
      style={{ contain: 'layout paint style' }}
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
          <MousePointerClick
            size={10}
            className='shrink-0 text-sky-700 dark:text-sky-400'
          />
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
      <div className='flex items-center gap-2.5 px-2.5 py-2 hover:bg-accent/40'>
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-md ring-1 ring-inset',
            category === 'flow'
              ? 'bg-purple-500/10 text-purple-600 ring-purple-500/20 dark:text-purple-400'
              : 'bg-blue-500/10 text-blue-600 ring-blue-500/20 dark:text-blue-400'
          )}
        >
          {runState === 'running' ? (
            <Loader2 size={14} className='animate-spin text-primary' />
          ) : runState === 'ok' ? (
            <CheckCircle2 size={14} className='text-emerald-500' />
          ) : runState === 'error' ? (
            <XCircle size={14} className='text-red-500' />
          ) : (
            <StepIcon type={step.type} size={14} />
          )}
        </span>

        <div className='min-w-0 flex-1 overflow-hidden'>
          <div className='flex flex-wrap items-center gap-1.5'>
            <span className='text-xs font-semibold leading-tight text-foreground'>
              {typeName}
            </span>
            <span
              className={cn(
                'rounded-md px-1.5 py-px text-[9px] font-medium',
                category === 'flow'
                  ? 'bg-purple-500/10 text-purple-700 dark:text-purple-300'
                  : 'bg-muted text-muted-foreground'
              )}
            >
              {categoryLabel}
            </span>
            {!title && selectorBadge && (
              <span className='rounded-md bg-muted px-1.5 py-px font-mono text-[9px] text-muted-foreground'>
                {selectorBadge}
              </span>
            )}
          </div>

          {secondRowMain && (
            <p
              className={cn(
                'mt-0.5 truncate text-[12px] leading-snug',
                title
                  ? 'font-medium text-foreground'
                  : runScenarioEmptyHint
                    ? 'text-muted-foreground'
                    : 'text-foreground/85'
              )}
              title={title || target || runScenarioEmptyHint}
            >
              {secondRowMain}
            </p>
          )}

          {description && (
            <p className='mt-0.5 truncate text-[10px] italic text-muted-foreground'>
              {description}
            </p>
          )}
        </div>

        {(() => {
          const imgSrc = step.type === 'tap' ? getTapStepImage(step) : '';
          return imgSrc ? (
            <img
              src={imgSrc}
              alt=''
              className='h-12 w-8 shrink-0 rounded border border-border/40 object-cover object-top'
            />
          ) : null;
        })()}

        <div className='flex shrink-0 items-center gap-0.5'>
          {onTogglePickTapCoords && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-all',
                coordPickActive === 'tap_point'
                  ? 'bg-sky-500/25 text-sky-800 dark:text-sky-300'
                  : 'opacity-0 hover:bg-sky-500/15 hover:text-sky-800 group-hover:opacity-100 dark:hover:text-sky-300'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickTapCoords();
              }}
              aria-label='Lấy tọa độ chạm trên mirror'
              title='Chạm trên mirror để điền tọa độ'
            >
              <MousePointerClick size={12} />
            </button>
          )}
          {onTogglePickSwipeCoords && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-all',
                coordPickActive === 'swipe_segment'
                  ? 'bg-sky-500/25 text-sky-800 dark:text-sky-300'
                  : 'opacity-0 hover:bg-sky-500/15 hover:text-sky-800 group-hover:opacity-100 dark:hover:text-sky-300'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickSwipeCoords();
              }}
              aria-label='Lấy tọa độ vuốt trên mirror'
              title='Vuốt trên mirror để điền đoạn vuốt'
            >
              <Move size={12} />
            </button>
          )}
          {onTogglePickSelector && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-all',
                isPickTarget
                  ? 'bg-amber-500/20 text-amber-700 dark:text-amber-300'
                  : 'opacity-0 hover:bg-amber-500/15 hover:text-amber-700 group-hover:opacity-100'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickSelector();
              }}
              aria-label='Chọn selector từ màn hình'
              title='Chọn selector từ mirror / cây UI'
            >
              <Crosshair size={12} />
            </button>
          )}
          {onRun && runState !== 'running' && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-opacity hover:bg-primary/10 hover:text-primary',
                compact ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onRun();
              }}
              aria-label='Chạy bước này'
              title='Chạy bước này trên thiết bị'
            >
              <Play size={12} />
            </button>
          )}
          {onStopInlineRun && runState === 'running' && (
            <button
              type='button'
              className='shrink-0 rounded-md p-1 hover:bg-destructive/15 hover:text-destructive'
              onClick={(e) => {
                e.stopPropagation();
                onStopInlineRun();
              }}
              aria-label='Dừng chạy thử'
              title='Dừng chạy thử'
            >
              <Square size={12} fill='currentColor' />
            </button>
          )}
          <button
            type='button'
            className='shrink-0 rounded-md p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100'
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            aria-label='Xóa bước'
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
