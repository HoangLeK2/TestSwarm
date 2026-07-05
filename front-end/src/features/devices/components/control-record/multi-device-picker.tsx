'use client';

import { useMemo } from 'react';
import { CheckSquare, Layers2, Smartphone, Square } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import {
  deviceSelectFullTitle,
  formatDeviceSelectLabel
} from '@/features/devices/lib/device-select-label';
import {
  isManualControlBlockedByAutomation
} from '@/features/devices/lib/control-record-device-state';

export type MultiDevicePickerOption = {
  brand: string;
  model: string;
  serial: string;
  state?: string | null;
  scenario_active?: number | null;
  manual_takeover_active?: boolean | null;
};

type MultiDevicePickerProps = {
  options: MultiDevicePickerOption[];
  selectedSerials: string[];
  onSelectedChange: (serials: string[]) => void;
  maxFollowers: number;
  maxTotalDevices: number;
  disabled?: boolean;
  disabledTitle?: string;
};

function isDeviceBusy(d: MultiDevicePickerOption) {
  return isManualControlBlockedByAutomation(d);
}

export function MultiDevicePicker({
  options,
  selectedSerials,
  onSelectedChange,
  maxFollowers,
  maxTotalDevices,
  disabled = false,
  disabledTitle
}: MultiDevicePickerProps) {
  const t = useTranslations('devicesControlRecord.view.multiControl');
  const tRecord = useTranslations('devicesControlRecord.view');
  const selectedSet = useMemo(
    () => new Set(selectedSerials),
    [selectedSerials]
  );

  const selectAllSerials = useMemo(
    () => options.map((d) => d.serial).slice(0, maxFollowers),
    [options, maxFollowers]
  );

  const allSelected =
    selectAllSerials.length > 0 &&
    selectAllSerials.every((serial) => selectedSet.has(serial));

  const toggleSerial = (serial: string) => {
    onSelectedChange(
      selectedSet.has(serial)
        ? selectedSerials.filter((s) => s !== serial)
        : selectedSerials.length >= maxFollowers
          ? selectedSerials
          : [...selectedSerials, serial]
    );
  };

  const selectAllLabel =
    options.length > maxFollowers
      ? t('selectUpToLimit', { count: maxTotalDevices })
      : t('selectAllReady');

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type='button'
          size='sm'
          variant={selectedSerials.length > 0 ? 'default' : 'outline'}
          className='h-8 shrink-0 gap-1.5 text-xs'
          disabled={disabled}
          title={disabled ? disabledTitle : undefined}
          aria-label={t('buttonLabel')}
        >
          <Layers2 className='size-3.5' />
          {t('buttonLabel')}
          {selectedSerials.length > 0 ? (
            <Badge
              variant='secondary'
              className='ml-0.5 h-4 rounded px-1 text-[10px]'
            >
              {selectedSerials.length + 1}
            </Badge>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='end'
        className='w-[min(420px,calc(100vw-2rem))] p-0'
      >
        <div className='space-y-1.5 border-b px-3 py-2.5'>
          <div className='flex items-center justify-between gap-3'>
            <p className='min-w-0 text-sm font-medium leading-snug'>
              {t('pickerTitle')}
            </p>
            <Badge
              variant='outline'
              className='shrink-0 text-[10px] tabular-nums'
            >
              {t('selectedSummary', {
                selected: selectedSerials.length,
                max: maxFollowers
              })}
            </Badge>
          </div>
          <p className='text-xs leading-snug text-muted-foreground'>
            {t('pickerHint')}
          </p>
        </div>

        <div className='flex flex-wrap gap-2 border-b px-3 py-2'>
          <Button
            type='button'
            size='sm'
            variant='secondary'
            className='h-7 text-xs'
            disabled={options.length === 0 || allSelected}
            onClick={() => onSelectedChange(selectAllSerials)}
          >
            {selectAllLabel}
          </Button>
          <Button
            type='button'
            size='sm'
            variant='ghost'
            className='h-7 text-xs'
            disabled={selectedSerials.length === 0}
            onClick={() => onSelectedChange([])}
          >
            {t('clearSelection')}
          </Button>
        </div>

        <div className='max-h-64 overflow-y-auto p-2'>
          {options.length === 0 ? (
            <p className='px-2 py-6 text-center text-xs text-muted-foreground'>
              {t('noReadyDevices')}
            </p>
          ) : (
            <ul
              className='space-y-0.5'
              role='listbox'
              aria-label={t('pickerTitle')}
            >
              {options.map((d) => {
                const checked = selectedSet.has(d.serial);
                const limitReached =
                  !checked && selectedSerials.length >= maxFollowers;
                const busy = isDeviceBusy(d);
                return (
                  <li key={d.serial}>
                    <button
                      type='button'
                      role='option'
                      aria-selected={checked}
                      disabled={limitReached}
                      onClick={() => toggleSerial(d.serial)}
                      title={deviceSelectFullTitle(d)}
                      className={cn(
                        'flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-2 text-left text-xs transition-colors',
                        'hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        checked && 'bg-primary/10',
                        limitReached && 'cursor-not-allowed opacity-50'
                      )}
                    >
                      <span className='flex size-7 shrink-0 items-center justify-center'>
                        {checked ? (
                          <CheckSquare className='size-4 text-primary' />
                        ) : (
                          <Square className='size-4 text-muted-foreground' />
                        )}
                      </span>
                      <Smartphone className='size-3.5 shrink-0 text-muted-foreground' />
                      <span className='min-w-0 flex-1'>
                        <span className='block truncate font-medium'>
                          {formatDeviceSelectLabel(d)}
                        </span>
                        <span className='block truncate font-mono text-[10px] text-muted-foreground'>
                          {d.serial}
                        </span>
                      </span>
                      {busy ? (
                        <Badge
                          variant='outline'
                          className='h-4 shrink-0 border-amber-400/40 bg-amber-400/10 px-1 text-[9px] font-medium text-amber-700 dark:text-amber-300'
                        >
                          {tRecord('deviceCampaignBadge')}
                        </Badge>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
