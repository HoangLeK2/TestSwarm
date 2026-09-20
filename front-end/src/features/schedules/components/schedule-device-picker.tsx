'use client';

import { useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Search,
  X
} from 'lucide-react';

import { useDevicePage } from '@/features/devices/hooks/use-devices';
import { useDebouncedCallback } from '@/hooks/use-debounced-callback';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';

const PAGE_SIZE = 8;
const SCHEDULE_DEVICE_PICKER_COPY_FALLBACKS = {
  devicePickerReadyHint: {
    en: 'Schedules normally run on ready devices. Check the status before selecting a phone.',
    vi: 'Lịch thường chạy trên thiết bị sẵn sàng. Hãy kiểm tra trạng thái trước khi chọn máy.'
  },
  devicePickerReadyState: {
    en: 'Ready',
    vi: 'Sẵn sàng'
  }
} as const;

type ScheduleDevicePickerCopyKey =
  keyof typeof SCHEDULE_DEVICE_PICKER_COPY_FALLBACKS;

function normalizeDeviceState(state: string | null | undefined) {
  return (state || 'UNKNOWN').trim().toUpperCase();
}

function isReadyLikeDeviceState(state: string | null | undefined) {
  const normalized = normalizeDeviceState(state);
  return normalized === 'READY' || normalized === 'ONLINE';
}

function translateDevicePickerCopy(
  t: (key: string) => string,
  locale: string,
  key: ScheduleDevicePickerCopyKey
) {
  try {
    const translated = t(key);
    if (
      translated &&
      translated !== key &&
      translated !== `schedulesFeature.form.${key}`
    ) {
      return translated;
    }
  } catch {
    // Use a readable fallback if the runtime message bundle is stale.
  }

  return SCHEDULE_DEVICE_PICKER_COPY_FALLBACKS[key][
    locale === 'en' ? 'en' : 'vi'
  ];
}

export function ScheduleDevicePicker({
  value,
  onChange
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations('schedulesFeature.form');
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const setQueryDebounced = useDebouncedCallback(
    (next: string) => setQuery(next),
    300
  );

  const { data } = useDevicePage({
    page,
    pageSize: PAGE_SIZE,
    q: query || undefined
  });
  const items = data?.items ?? [];
  const pageCount = Math.max(1, data?.page_count ?? 1);
  const readyHint = translateDevicePickerCopy(
    t,
    locale,
    'devicePickerReadyHint'
  );
  const readyStateLabel = translateDevicePickerCopy(
    t,
    locale,
    'devicePickerReadyState'
  );

  useEffect(() => {
    setPage(1);
  }, [query]);

  // Labels accumulate as pages load; serials we have never seen (reopening an
  // old schedule) fall back to the serial itself rather than an extra request.
  const labels = useRef(new Map<string, string>());
  for (const device of items) {
    labels.current.set(device.serial, device.name || device.serial);
  }

  const toggle = (serial: string) => {
    onChange(
      value.includes(serial)
        ? value.filter((s) => s !== serial)
        : [...value, serial]
    );
  };

  return (
    <div className='space-y-2'>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant='outline'
            role='combobox'
            aria-expanded={open}
            className='w-full justify-between'
          >
            <span className='truncate'>
              {value.length
                ? t('devicePickerSelected', { count: value.length })
                : t('devicePickerPlaceholder')}
            </span>
            <ChevronsUpDown className='size-4 opacity-50' />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align='start'
          className='z-[10001] w-[var(--radix-popover-trigger-width)] p-2'
        >
          <p className='mb-2 rounded-md bg-muted/40 px-2.5 py-2 text-xs leading-5 text-muted-foreground'>
            {readyHint}
          </p>
          <div className='relative'>
            <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setQueryDebounced(event.target.value.trim());
              }}
              placeholder={t('devicePickerSearch')}
              className='h-8 pl-8'
            />
          </div>
          <div className='mt-2 max-h-64 overflow-y-auto'>
            {items.length ? (
              items.map((device) => {
                const state = normalizeDeviceState(device.state);
                const readyLike = isReadyLikeDeviceState(device.state);

                return (
                  <button
                    key={device.serial}
                    type='button'
                    className='flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground'
                    onClick={() => toggle(device.serial)}
                  >
                    <Checkbox
                      checked={value.includes(device.serial)}
                      tabIndex={-1}
                      className='pointer-events-none'
                    />
                    <span className='min-w-0 flex-1'>
                      <span className='flex min-w-0 items-center gap-2'>
                        <span className='min-w-0 flex-1 truncate'>
                          {device.name || device.serial}
                        </span>
                        <Badge
                          variant={readyLike ? 'default' : 'secondary'}
                          className='h-5 shrink-0 text-[10px]'
                        >
                          {readyLike ? readyStateLabel : state}
                        </Badge>
                      </span>
                      <span className='block truncate text-[11px] text-muted-foreground'>
                        {[device.brand, device.model].filter(Boolean).join(' ')}
                        {' · '}
                        {device.serial}
                      </span>
                    </span>
                  </button>
                );
              })
            ) : (
              <p className='px-2 py-6 text-center text-sm text-muted-foreground'>
                {t('devicePickerEmpty')}
              </p>
            )}
          </div>
          {pageCount > 1 && (
            <div className='mt-2 flex items-center justify-between border-t pt-2 text-xs text-muted-foreground'>
              <Button
                type='button'
                variant='ghost'
                size='icon'
                className='size-7'
                aria-label={t('targetPreviousPage')}
                disabled={page <= 1}
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
              >
                <ChevronLeft className='size-4' />
              </Button>
              <span>{t('targetPageStatus', { page, total: pageCount })}</span>
              <Button
                type='button'
                variant='ghost'
                size='icon'
                className='size-7'
                aria-label={t('targetNextPage')}
                disabled={page >= pageCount}
                onClick={() => setPage((prev) => Math.min(pageCount, prev + 1))}
              >
                <ChevronRight className='size-4' />
              </Button>
            </div>
          )}
        </PopoverContent>
      </Popover>

      {value.length > 0 && (
        <div className='flex flex-wrap items-center gap-1.5'>
          {value.map((serial) => (
            <span
              key={serial}
              className='inline-flex items-center gap-1 rounded-full border bg-muted/50 py-0.5 pl-2 pr-1 text-xs'
            >
              <span className='max-w-[12rem] truncate'>
                {labels.current.get(serial) ?? serial}
              </span>
              <button
                type='button'
                aria-label={serial}
                className='rounded-full p-0.5 hover:bg-muted'
                onClick={() => toggle(serial)}
              >
                <X className='size-3' />
              </button>
            </span>
          ))}
          <Button
            type='button'
            variant='ghost'
            size='sm'
            className='h-6 px-2 text-xs'
            onClick={() => onChange([])}
          >
            {t('devicePickerClear')}
          </Button>
        </div>
      )}
    </div>
  );
}
