'use client';

import { Fragment, type ReactNode } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { FLOW_ROW_DRAG_GUTTER_CLASS } from './flow-row-gutter';
import { createDefaultStep, type FlowStep } from '../scenario-steps/types';
import { StepIcon } from './step-icon';
import { useCampaignFlowI18n } from './flow-i18n';

interface Props {
  onInsert: (step: FlowStep) => void;
}

function InsertStepDropdown({
  onInsert,
  trigger,
  contentSide = 'right',
  contentAlign = 'start',
  sideOffset = 10,
}: {
  onInsert: (step: FlowStep) => void;
  trigger: ReactNode;
  contentSide?: 'top' | 'right' | 'bottom' | 'left';
  contentAlign?: 'start' | 'center' | 'end';
  sideOffset?: number;
}) {
  const { getInsertMenu, tInsert } = useCampaignFlowI18n();
  const insertMenu = getInsertMenu();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent
        side={contentSide}
        align={contentAlign}
        sideOffset={sideOffset}
        className='max-h-[min(22rem,75vh)] w-[min(18rem,calc(100vw-2rem))] overflow-y-auto p-1.5'
      >
        {insertMenu.map((group, gi) => (
          <Fragment key={group.group}>
            {gi > 0 ? <DropdownMenuSeparator /> : null}
            <DropdownMenuLabel className='px-2.5 pb-0.5 pt-2'>
              <span className='block text-[11px] font-bold text-foreground'>{group.group}</span>
              {'description' in group && (
                <span className='block text-[10px] font-normal text-muted-foreground'>{(group as any).description}</span>
              )}
            </DropdownMenuLabel>
            {group.items.map((item) => (
              <DropdownMenuItem
                key={item.type}
                className='cursor-pointer gap-2.5 py-2.5 pl-2.5 pr-2 text-sm'
                onSelect={() => onInsert(createDefaultStep(item.type))}
              >
                <StepIcon type={item.type} size={12} />
                <span>{item.label}</span>
              </DropdownMenuItem>
            ))}
          </Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function InsertButton({ onInsert }: Props) {
  const { tInsert } = useCampaignFlowI18n();
  return (
    <div className='flex min-h-7 justify-end py-0.5 pr-0.5'>
      <InsertStepDropdown
        onInsert={onInsert}
        contentSide='right'
        contentAlign='start'
        trigger={
          <Button
            type='button'
            variant='outline'
            size='icon'
            className='size-7 shrink-0 rounded-full border border-dashed border-muted-foreground/40 text-muted-foreground hover:border-primary hover:text-primary'
            aria-label={tInsert('addStepAria')}
          >
            <Plus className='size-3' strokeWidth={2} />
          </Button>
        }
      />
    </div>
  );
}

/**
 * One insert zone per gap between steps. Notion-style: thin lines + centered +, aligned with step cards (same left offset as drag handle).
 */
export function InsertGap({
  onInsert,
  alignWithDragHandle = true,
}: Props & { alignWithDragHandle?: boolean }) {
  const { tInsert } = useCampaignFlowI18n();
  const track = (
    <div
      className={cn(
        'group/ig -my-px flex min-h-7 cursor-default items-center gap-0 py-0.5',
      )}
    >
      <div
        className={cn(
          'h-px min-w-0 flex-1 bg-border transition-opacity duration-150',
          'opacity-0 group-hover/ig:opacity-100 max-md:opacity-35',
        )}
        aria-hidden
      />
      <div className='shrink-0 px-0.5'>
        <InsertStepDropdown
          onInsert={onInsert}
          contentSide='bottom'
          contentAlign='center'
          sideOffset={6}
          trigger={
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className={cn(
                'size-6 shrink-0 rounded-full text-muted-foreground shadow-none',
                'ring-1 ring-border/60 bg-background/90 backdrop-blur-[1px]',
                'transition-[opacity,transform,background-color,color,box-shadow] duration-150',
                'hover:bg-muted hover:text-foreground hover:ring-border',
                'max-md:opacity-80',
                'md:opacity-0 md:group-hover/ig:opacity-100',
                'focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring',
                'motion-safe:md:group-hover/ig:scale-[1.03]',
              )}
              aria-label={tInsert('addStepAria')}
            >
              <Plus className='size-3.5' strokeWidth={2} />
            </Button>
          }
        />
      </div>
      <div
        className={cn(
          'h-px min-w-0 flex-1 bg-border transition-opacity duration-150',
          'opacity-0 group-hover/ig:opacity-100 max-md:opacity-35',
        )}
        aria-hidden
      />
    </div>
  );

  if (!alignWithDragHandle) {
    return track;
  }

  return (
    <div className='flex min-h-7 items-stretch'>
      <div className={cn(FLOW_ROW_DRAG_GUTTER_CLASS, 'shrink-0')} aria-hidden />
      <div className='min-w-0 flex-1'>{track}</div>
    </div>
  );
}
