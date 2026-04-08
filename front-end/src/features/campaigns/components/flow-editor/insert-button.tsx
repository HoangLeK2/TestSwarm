'use client';

import { Fragment } from 'react';
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
import { INSERT_MENU } from './constants';
import { createDefaultStep, type FlowStep } from '../scenario-steps/types';
import { StepIcon } from './step-icon';

interface Props {
  onInsert: (step: FlowStep) => void;
}

export function InsertButton({ onInsert }: Props) {
  return (
    <div className='flex min-h-7 justify-end py-0.5 pr-0.5'>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type='button'
            variant='outline'
            size='icon'
            className='size-7 shrink-0 rounded-full border border-dashed border-muted-foreground/40 text-muted-foreground hover:border-primary hover:text-primary'
            aria-label='Thêm bước'
          >
            <Plus className='size-3' strokeWidth={2} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side='right'
          align='start'
          sideOffset={10}
          className='max-h-[min(22rem,75vh)] w-[min(18rem,calc(100vw-2rem))] overflow-y-auto p-1.5'
        >
          {INSERT_MENU.map((group, gi) => (
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
    </div>
  );
}
