'use client';

import { MoreHorizontal } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';

import { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TitleTooltip } from '@/components/title-tooltip';

const MAX_ACTIONS = 2;

export interface ActionItem<T> {
  label: string | React.ReactNode;
  icon: LucideIcon;
  onClick: (data: T) => void;
  disabled?: boolean | ((data: T) => boolean);
  variant?:
    | 'default'
    | 'destructive'
    | ((data: T) => 'default' | 'destructive');
  className?: string | ((data: T) => string);
  hidden?: boolean | ((data: T) => boolean);
}

interface CellActionProps<T> {
  data: T;
  actions: ActionItem<T>[];
  isLoading?: boolean;
  align?: 'start' | 'end';
}

export function CellAction<T>({
  data,
  actions,
  isLoading = false,
  align = 'end'
}: CellActionProps<T>) {
  if (actions.length < MAX_ACTIONS) {
    return (
      <div className='flex gap-2'>
        {actions.map((action) => {
          const mappedAction = {
            ...action,
            isDisabled:
              typeof action.disabled === 'function'
                ? action.disabled(data)
                : action.disabled,
            variant:
              typeof action.variant === 'function'
                ? action.variant(data)
                : action.variant,
            className: cn(
              typeof action.className === 'function'
                ? action.className(data)
                : action.className,
              (typeof action.variant === 'function'
                ? action.variant(data)
                : action.variant) === 'destructive'
            )
          };
          if (
            typeof mappedAction.hidden === 'function' &&
            mappedAction.hidden(data)
          ) {
            return null;
          }
          return (
            <TitleTooltip
              content={mappedAction.label}
              key={mappedAction?.label as string}
            >
              <Button
                size='icon'
                variant={
                  mappedAction.variant === 'destructive'
                    ? 'destructive-ghost'
                    : mappedAction.variant || 'ghost'
                }
                className={cn(mappedAction.className)}
                onClick={() => mappedAction.onClick(data)}
                disabled={isLoading || mappedAction.isDisabled}
              >
                <mappedAction.icon className='h-4 w-4 text-inherit' />
              </Button>
            </TitleTooltip>
          );
        })}
      </div>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant='ghost' className='h-8 w-8 p-0' disabled={isLoading}>
          <span className='sr-only'>Open menu</span>
          <MoreHorizontal className='h-4 w-4' />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align}>
        {actions.map((action, index) => {
          const isLast = index === actions.length - 1;
          const isHidden =
            typeof action.hidden === 'function' && action.hidden(data);
          if (isHidden) {
            return null;
          }
          return (
            <>
              <DropdownMenuItem
                key={action.label as string}
                onClick={() => action.onClick(data)}
                disabled={
                  typeof action.disabled === 'function'
                    ? action.disabled(data)
                    : action.disabled
                }
                className={cn(
                  typeof action.className === 'function'
                    ? action.className(data)
                    : action.className,
                  action.variant === 'destructive' &&
                    'hover:outline-destructive/20'
                )}
                variant={
                  typeof action.variant === 'function'
                    ? action.variant(data)
                    : action.variant
                }
              >
                <action.icon className='mr-2 h-4 w-4 text-inherit' />
                {action.label as string}
              </DropdownMenuItem>
              {!isLast && !isHidden && <DropdownMenuSeparator />}
            </>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
