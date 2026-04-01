'use client';

import { Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import { STEP_COLORS, getStepTypeName, getStepDisplay, getStepCategory } from './constants';
import { StepIcon } from './step-icon';

interface Props {
  step: FlowStep;
  index: number;
  selected: boolean;
  onClick: () => void;
  onRemove: () => void;
}

export function StepCard({ step, selected, onClick, onRemove }: Props) {
  const colorCls = STEP_COLORS[step.type] ?? 'border-l-gray-400';
  const typeName = getStepTypeName(step.type);
  const { target, selectorBadge } = getStepDisplay(step);
  const category = getStepCategory(step.type);

  // User-defined title/description override auto-generated display
  const title = (step.title as string | undefined)?.trim() || undefined;
  const description = (step.description as string | undefined)?.trim() || undefined;

  return (
    <div
      className={cn(
        'group rounded-md border-l-[3px] border bg-card transition-all cursor-pointer',
        colorCls,
        selected && 'ring-2 ring-primary/40 bg-accent/30',
      )}
      onClick={onClick}
    >
      <div className='flex items-center gap-2 px-2.5 py-1.5 hover:bg-accent/50'>
        <StepIcon type={step.type} size={12} className='shrink-0' />

        <div className='min-w-0 flex-1 overflow-hidden'>
          {/* Row 1: type name + category badge */}
          <div className='flex items-center gap-1.5'>
            <span className='text-[10px] font-bold uppercase tracking-wide text-muted-foreground leading-tight'>
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
          {(title || target) && (
            <div className='mt-0.5 flex items-center gap-1 overflow-hidden'>
              {!title && selectorBadge && (
                <span className='flex-shrink-0 rounded bg-muted px-1 py-px font-mono text-[9px] text-muted-foreground'>
                  {selectorBadge}
                </span>
              )}
              <span
                className={cn(
                  'truncate text-[12px] font-medium leading-tight',
                  title ? 'text-foreground' : 'text-foreground/80',
                )}
                title={title || target}
              >
                {title || target}
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
