'use client';

import { useState } from 'react';
import { Braces, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export type VariableInsertMenuItem = {
  value: string;
  label?: string;
  code?: string;
  badge?: string;
  description?: string;
  detail?: string;
};

export type VariableInsertMenuGroup = {
  label: string;
  items: VariableInsertMenuItem[];
};

export function VariableInsertMenu({
  groups,
  onInsert,
  label,
  ariaLabel,
  className,
  triggerClassName,
  align = 'end',
  disabled = false,
  fullWidth = false
}: {
  groups: VariableInsertMenuGroup[];
  onInsert: (value: string) => void;
  label: string;
  ariaLabel?: string;
  className?: string;
  triggerClassName?: string;
  align?: 'start' | 'center' | 'end';
  disabled?: boolean;
  fullWidth?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const visibleGroups = groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => item.value)
    }))
    .filter((group) => group.items.length > 0);

  if (visibleGroups.length === 0) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type='button'
          size='sm'
          variant='outline'
          disabled={disabled}
          aria-label={ariaLabel ?? label}
          className={cn(
            'h-8 min-w-[8.5rem] justify-between gap-2 px-2 text-[11px] font-medium',
            fullWidth && 'w-full',
            triggerClassName
          )}
        >
          <span className='flex min-w-0 items-center gap-1.5'>
            <Braces className='h-3.5 w-3.5 shrink-0' />
            <span className='truncate'>{label}</span>
          </span>
          <ChevronDown className='h-3 w-3 shrink-0 opacity-60' />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align={align}
        showPortal={false}
        className={cn(
          'z-[calc(var(--z-floating)+100)] w-[min(20rem,calc(100vw-2rem))] overflow-hidden p-0',
          className
        )}
      >
        <Command>
          <CommandList
            className='max-h-64 overflow-y-auto overscroll-contain'
            onWheel={(event) => event.stopPropagation()}
            onTouchMove={(event) => event.stopPropagation()}
          >
            {visibleGroups.map((group) => (
              <CommandGroup key={group.label} heading={group.label}>
                {group.items.map((item) => (
                  <CommandItem
                    key={`${group.label}:${item.value}`}
                    value={item.value}
                    onSelect={() => {
                      onInsert(item.value);
                      setOpen(false);
                    }}
                    className='items-start px-2 py-2.5'
                  >
                    <div className='flex w-full min-w-0 flex-col gap-1'>
                      {item.label || item.badge ? (
                        <div className='flex min-w-0 items-center gap-2'>
                          <span className='min-w-0 flex-1 text-xs font-medium leading-snug text-foreground'>
                            {item.label ?? item.code ?? item.value}
                          </span>
                          {item.badge ? (
                            <span className='shrink-0 rounded border bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground'>
                              {item.badge}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                      <code
                        className={cn(
                          'max-w-full break-all font-mono font-medium leading-snug',
                          item.label || item.badge
                            ? 'text-[10px] text-muted-foreground'
                            : 'text-[11px] text-foreground'
                        )}
                      >
                        {item.code ?? item.value}
                      </code>
                      {item.description ? (
                        <span className='max-w-full text-[10px] leading-snug text-muted-foreground'>
                          {item.description}
                        </span>
                      ) : null}
                      {item.detail ? (
                        <span className='max-w-full text-[10px] leading-snug text-muted-foreground/80'>
                          {item.detail}
                        </span>
                      ) : null}
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
