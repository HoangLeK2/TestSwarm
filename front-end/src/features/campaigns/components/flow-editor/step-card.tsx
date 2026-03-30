'use client';

import { Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import { STEP_COLORS, getStepTypeName, getStepSummary } from './constants';
import { StepIcon } from './step-icon';
import type { SelectorPickTarget } from './selector-pick';
import { isSelectorPickableStep, selectorPickTargetEquals } from './selector-pick';
import { useTranslations } from 'next-intl';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface Props {
  step: FlowStep;
  index: number;
  selected: boolean;
  onClick: () => void;
  onRemove: () => void;
  stepPath?: SelectorPickTarget;
  selectorPickTarget?: SelectorPickTarget | null;
  onTogglePickSelector?: (path: SelectorPickTarget) => void;
}

export function StepCard({
  step,
  index: _index,
  selected,
  onClick,
  onRemove,
  stepPath,
  selectorPickTarget,
  onTogglePickSelector,
}: Props) {
  const t = useTranslations('devicesControlRecord.view');
  const colorCls = STEP_COLORS[step.type] ?? 'border-l-gray-400';
  const typeName = getStepTypeName(step.type);
  const summary = getStepSummary(step);
  const picking =
    stepPath && selectorPickTarget && selectorPickTargetEquals(selectorPickTarget, stepPath);
  const pickOnClick = Boolean(stepPath && onTogglePickSelector && isSelectorPickableStep(step));

  const handleRowClick = () => {
    if (pickOnClick) {
      onTogglePickSelector!(stepPath!);
    }
    onClick();
  };

  const tooltipBody = picking
    ? t('tooltipStepSelectorPicking')
    : pickOnClick
      ? t('tooltipStepSelectorPick')
      : t('tooltipStepDefault');

  return (
    <div
      className={cn(
        'group rounded-md border-l-[3px] border bg-card transition-all',
        colorCls,
        selected && 'ring-2 ring-primary/40 bg-accent/30',
        picking && 'ring-2 ring-amber-500/80 bg-amber-500/5 shadow-[0_0_0_1px_rgba(245,158,11,0.35)]',
        pickOnClick && 'cursor-crosshair',
      )}
    >
      <div className='flex cursor-pointer items-center gap-2 px-2.5 py-1.5 hover:bg-accent/50'>
        <Tooltip delayDuration={400}>
          <TooltipTrigger asChild>
            <div
              className='flex min-w-0 flex-1 items-center gap-2'
              onClick={handleRowClick}
            >
              <StepIcon type={step.type} size={12} />
              <div className='min-w-0 flex-1 overflow-hidden'>
                <div className='flex items-center gap-1.5'>
                  <span className='text-[11px] font-semibold leading-tight'>{typeName}</span>
                  {picking && (
                    <span className='rounded-full bg-amber-500/20 px-1.5 py-px text-[9px] font-bold uppercase tracking-wide text-amber-800 dark:text-amber-200'>
                      {t('pickTargetActive')}
                    </span>
                  )}
                </div>
                {summary && (
                  <span className='block truncate text-[10px] text-muted-foreground' title={summary}>
                    {summary}
                  </span>
                )}
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent
            side='top'
            sideOffset={6}
            className='max-w-[min(100vw-2rem,22rem)] border border-border/80 bg-popover px-3 py-2 text-xs leading-relaxed text-popover-foreground shadow-md'
          >
            {tooltipBody}
          </TooltipContent>
        </Tooltip>

        <Tooltip delayDuration={300}>
          <TooltipTrigger asChild>
            <button
              type='button'
              className='shrink-0 rounded p-0.5 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100'
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              aria-label={t('tooltipDeleteStep')}
            >
              <Trash2 size={11} />
            </button>
          </TooltipTrigger>
          <TooltipContent side='left' className='text-xs'>
            {t('tooltipDeleteStep')}
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
