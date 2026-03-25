'use client';

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CaretSortIcon,
  Cross2Icon
} from '@radix-ui/react-icons';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';

type SyncedValue = 'synced' | 'not_synced' | null;

type Option = { label: string; value: string };

interface DataTableStatusFilterHeaderProps {
  title: string;
  value?: SyncedValue | string[] | string | null;
  onChange: (value: SyncedValue | string[] | string | undefined | null) => void;
  syncedLabel?: string;
  notSyncedLabel?: string;
  options?: Option[];
  multiple?: boolean;
}

export function DataTableStatusFilterHeader({
  value,
  onChange,
  title,
  syncedLabel,
  notSyncedLabel,
  options,
  multiple
}: DataTableStatusFilterHeaderProps) {
  const tCommon = useTranslations('common');
  const defaultSyncedLabel = syncedLabel || tCommon('status.synced');
  const defaultNotSyncedLabel = notSyncedLabel || tCommon('status.not_synced');

  const hasOptions = options && options.length > 0;

  const currentValue = multiple
    ? Array.isArray(value)
      ? (value as string[])
      : []
    : Array.isArray(value)
      ? value[0]
      : (value as string | undefined);
  const selectedValues = multiple
    ? new Set(Array.isArray(value) ? (value as string[]) : [])
    : new Set(value ? [value as string] : []);

  const isDesc = value === 'synced';
  const isAsc = value === 'not_synced';
  const isFiltered = hasOptions
    ? multiple
      ? selectedValues.size > 0
      : currentValue !== undefined
    : value !== null && value !== undefined;

  const toggleOptionValue = (val: string) => {
    if (!hasOptions) return;
    if (multiple) {
      const next = new Set(selectedValues);
      if (next.has(val)) next.delete(val);
      else next.add(val);
      const result = Array.from(next);
      onChange(result.length > 0 ? result : undefined);
    } else {
      const newValue = currentValue === val ? undefined : val;
      onChange(newValue || undefined);
    }
  };

  const reset = () => onChange(undefined);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          '-ml-1.5 flex h-8 items-center gap-1.5 rounded-md px-2 py-1.5 hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring data-[state=open]:bg-accent [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground'
        )}
      >
        {title}
        {hasOptions ? (
          <CaretSortIcon />
        ) : isDesc ? (
          <ChevronDownIcon />
        ) : isAsc ? (
          <ChevronUpIcon />
        ) : (
          <CaretSortIcon />
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='w-48'>
        {!hasOptions && (
          <>
            <DropdownMenuCheckboxItem
              className='relative whitespace-nowrap pl-2 pr-8 [&>span:first-child]:left-auto [&>span:first-child]:right-2 [&_svg]:text-muted-foreground'
              checked={isAsc}
              onClick={() => onChange('not_synced')}
            >
              <ChevronUpIcon />
              {defaultNotSyncedLabel}
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              className='relative whitespace-nowrap pl-2 pr-8 [&>span:first-child]:left-auto [&>span:first-child]:right-2 [&_svg]:text-muted-foreground'
              checked={isDesc}
              onClick={() => onChange('synced')}
            >
              <ChevronDownIcon />
              {defaultSyncedLabel}
            </DropdownMenuCheckboxItem>
          </>
        )}
        {hasOptions &&
          options.map((opt) => {
            const isChecked = multiple
              ? selectedValues.has(opt.value)
              : currentValue === opt.value;
            return (
              <DropdownMenuCheckboxItem
                key={opt.value}
                className='relative whitespace-nowrap pl-2 pr-8 [&>span:first-child]:left-auto [&>span:first-child]:right-2 [&_svg]:text-muted-foreground'
                checked={isChecked}
                onClick={() => toggleOptionValue(opt.value)}
              >
                {opt.label}
              </DropdownMenuCheckboxItem>
            );
          })}
        {isFiltered && (
          <DropdownMenuItem
            className='pl-2 [&_svg]:text-muted-foreground'
            onClick={reset}
          >
            <Cross2Icon />
            {tCommon('reset')}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
