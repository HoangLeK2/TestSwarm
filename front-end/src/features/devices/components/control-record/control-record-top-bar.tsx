'use client';

import { ArrowLeft } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Device } from '@/features/devices/types';

import { DeviceSelectPicker } from './device-select-picker';
import { MultiDevicePicker } from './multi-device-picker';

type ControlRecordTopBarLabels = {
  editingScenario: string;
  templateBadge: string;
  backToMainScenario: string;
  selectPhonePlaceholder: string;
  deviceLabel: string;
  deviceCampaignBadge: string;
  wsConnected: string;
  wsDisconnected: string;
};

type ControlRecordTopBarProps = {
  title: string;
  eyebrow: string;
  labels: ControlRecordTopBarLabels;
  editing: boolean;
  template: boolean;
  showRecoveryBack: boolean;
  onRecoveryBack: () => void;
  devices: Device[];
  deviceSelectValue: string;
  onDeviceChange: (serial: string | null) => void;
  multiFollowerOptions: Device[];
  multiFollowerSerials: string[];
  onMultiFollowerSerialsChange: (serials: string[]) => void;
  maxMultiFollowers: number;
  maxMultiDevices: number;
  multiPickerDisabled: boolean;
  multiPickerDisabledTitle?: string;
  wsConnected: boolean;
};

export function ControlRecordTopBar({
  title,
  eyebrow,
  labels,
  editing,
  template,
  showRecoveryBack,
  onRecoveryBack,
  devices,
  deviceSelectValue,
  onDeviceChange,
  multiFollowerOptions,
  multiFollowerSerials,
  onMultiFollowerSerialsChange,
  maxMultiFollowers,
  maxMultiDevices,
  multiPickerDisabled,
  multiPickerDisabledTitle,
  wsConnected
}: ControlRecordTopBarProps) {
  return (
    <div className='flex min-w-0 shrink-0 flex-col gap-2 overflow-hidden border-b bg-background px-3 py-2 md:flex-row md:items-center md:gap-3'>
      <div className='flex min-w-0 items-center gap-2 md:flex-1'>
        <div className='min-w-0 flex-1'>
          <div className='flex min-w-0 items-center gap-2'>
            <p className='truncate text-sm font-semibold leading-tight'>
              {title}
            </p>
            {editing ? (
              <Badge
                variant='outline'
                className='shrink-0 border-amber-400/40 bg-amber-400/10 text-[10px] font-medium text-amber-700 dark:text-amber-300'
              >
                {labels.editingScenario}
              </Badge>
            ) : null}
            {template ? (
              <span className='inline-flex shrink-0 items-center rounded-full border border-emerald-400/40 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300'>
                {labels.templateBadge}
              </span>
            ) : null}
          </div>
          <p className='text-[10px] text-muted-foreground'>{eyebrow}</p>
        </div>

        {showRecoveryBack ? (
          <Button
            variant='outline'
            size='sm'
            className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
            onClick={onRecoveryBack}
          >
            <ArrowLeft className='size-3.5' />
            {labels.backToMainScenario}
          </Button>
        ) : null}
      </div>

      <div className='hidden h-6 w-px shrink-0 bg-border md:block' />

      <div className='flex min-w-0 items-center gap-1.5 md:shrink'>
        <span className='hidden shrink-0 text-[10px] font-medium uppercase tracking-wide text-muted-foreground xl:inline'>
          {labels.deviceLabel}
        </span>
        <div className='min-w-0 flex-1 md:max-w-[min(240px,calc(100vw-16rem))]'>
          <DeviceSelectPicker
            devices={devices}
            value={deviceSelectValue}
            onChange={onDeviceChange}
            placeholder={labels.selectPhonePlaceholder}
            busyBadgeLabel={labels.deviceCampaignBadge}
          />
        </div>

        <MultiDevicePicker
          options={multiFollowerOptions}
          selectedSerials={multiFollowerSerials}
          onSelectedChange={onMultiFollowerSerialsChange}
          maxFollowers={maxMultiFollowers}
          maxTotalDevices={maxMultiDevices}
          disabled={multiPickerDisabled}
          disabledTitle={multiPickerDisabledTitle}
        />
      </div>

      <Badge
        variant='outline'
        className={cn(
          'h-8 shrink-0 gap-1.5 rounded-full px-2.5 text-[11px] font-medium',
          wsConnected
            ? 'border-transparent bg-transparent px-1.5 text-muted-foreground shadow-none'
            : 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400'
        )}
      >
        <span
          className={cn(
            'size-1.5 rounded-full',
            wsConnected ? 'bg-green-500' : 'bg-red-500'
          )}
        />
        {wsConnected ? labels.wsConnected : labels.wsDisconnected}
      </Badge>
    </div>
  );
}
