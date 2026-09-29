'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  Smartphone
} from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import type { Device } from '@/features/devices/types';
import {
  deviceSelectDisplayName,
  deviceSelectFullTitle,
  formatDeviceSelectLabel
} from '@/features/devices/lib/device-select-label';
import { isManualControlBlockedByAutomation } from '@/features/devices/lib/control-record-device-state';

const PAGE_SIZE = 6;

type DeviceSelectPickerProps = {
  devices: Device[];
  value: string;
  onChange: (serial: string | null) => void;
  placeholder: string;
  busyBadgeLabel: string;
  className?: string;
};

function matchesQuery(d: Device, q: string) {
  if (!q) return true;
  const haystack =
    `${d.name ?? ''} ${d.display_name ?? ''} ${d.brand ?? ''} ${d.model ?? ''} ${d.serial}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => haystack.includes(token));
}

export function DeviceSelectPicker({
  devices,
  value,
  onChange,
  placeholder,
  busyBadgeLabel,
  className
}: DeviceSelectPickerProps) {
  const t = useTranslations('devicesControlRecord.view.devicePicker');
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);

  const filtered = useMemo(
    () => devices.filter((d) => matchesQuery(d, query.trim())),
    [devices, query]
  );

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(
    safePage * PAGE_SIZE,
    safePage * PAGE_SIZE + PAGE_SIZE
  );

  useEffect(() => {
    setPage(0);
  }, [query]);

  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const selected = devices.find((d) => d.serial === value) ?? null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id='control-record-device-select'
          type='button'
          variant='outline'
          role='combobox'
          aria-expanded={open}
          title={selected ? deviceSelectFullTitle(selected) : placeholder}
          className={cn(
            'h-8 w-full min-w-0 max-w-full justify-between gap-1.5 overflow-hidden px-3 text-xs font-normal',
            !selected && 'text-muted-foreground',
            className
          )}
        >
          <span className='min-w-0 truncate text-left'>
            {selected ? formatDeviceSelectLabel(selected) : placeholder}
          </span>
          <ChevronDown className='size-3.5 shrink-0 opacity-50' />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        align='start'
        className='w-[min(420px,calc(100vw-2rem))] p-0'
      >
        <div className='relative border-b p-2'>
          <Search className='pointer-events-none absolute left-4 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('searchPlaceholder')}
            className='h-8 pl-8 text-xs'
            aria-label={t('searchPlaceholder')}
          />
        </div>

        <div className='max-h-[240px] overflow-y-auto p-1.5'>
          {pageItems.length === 0 ? (
            <p className='px-2 py-6 text-center text-xs text-muted-foreground'>
              {t('noResults')}
            </p>
          ) : (
            <ul className='space-y-0.5' role='listbox'>
              {pageItems.map((d) => {
                const active = d.serial === value;
                return (
                  <li key={d.serial}>
                    <button
                      type='button'
                      role='option'
                      aria-selected={active}
                      title={deviceSelectFullTitle(d)}
                      onClick={() => {
                        onChange(d.serial);
                        setOpen(false);
                      }}
                      className={cn(
                        'flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                        'hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        active && 'bg-primary/10'
                      )}
                    >
                      <Smartphone className='size-3.5 shrink-0 text-muted-foreground' />
                      <span className='min-w-0 flex-1'>
                        <span className='block truncate font-medium'>
                          {deviceSelectDisplayName(d) || d.serial}
                        </span>
                        <span className='block truncate font-mono text-[10px] text-muted-foreground'>
                          {d.serial}
                        </span>
                      </span>
                      {isManualControlBlockedByAutomation(d) ? (
                        <Badge
                          variant='outline'
                          className='h-4 shrink-0 border-amber-400/40 bg-amber-400/10 px-1 text-[9px] font-medium text-amber-700 dark:text-amber-300'
                        >
                          {busyBadgeLabel}
                        </Badge>
                      ) : null}
                      <Check
                        className={cn(
                          'size-3.5 shrink-0 text-primary',
                          active ? 'opacity-100' : 'opacity-0'
                        )}
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {filtered.length > PAGE_SIZE ? (
          <div className='flex items-center justify-between gap-2 border-t px-2 py-1.5'>
            <span className='truncate text-[10px] tabular-nums text-muted-foreground'>
              {t('pageSummary', {
                from: safePage * PAGE_SIZE + 1,
                to: safePage * PAGE_SIZE + pageItems.length,
                total: filtered.length
              })}
            </span>
            <div className='flex shrink-0 items-center gap-1'>
              <Button
                type='button'
                size='icon'
                variant='ghost'
                className='size-6'
                disabled={safePage === 0}
                aria-label={t('previousPage')}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft className='size-3.5' />
              </Button>
              <span className='text-[10px] tabular-nums text-muted-foreground'>
                {safePage + 1}/{pageCount}
              </span>
              <Button
                type='button'
                size='icon'
                variant='ghost'
                className='size-6'
                disabled={safePage >= pageCount - 1}
                aria-label={t('nextPage')}
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              >
                <ChevronRight className='size-3.5' />
              </Button>
            </div>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
