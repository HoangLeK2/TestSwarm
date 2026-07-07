'use client';

import { ArrowLeft, GitBranch, List } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { Device } from '@/features/devices/types';
import {
  deviceSelectFullTitle,
  formatDeviceSelectLabel
} from '@/features/devices/lib/device-select-label';
import { isManualControlBlockedByAutomation } from '@/features/devices/lib/control-record-device-state';

import { MultiDevicePicker } from './multi-device-picker';

type ControlRecordTopBarLabels = {
  editingScenario: string;
  templateBadge: string;
  backToMainScenario: string;
  selectPhonePlaceholder: string;
  deviceCampaignBadge: string;
  wsConnected: string;
  wsDisconnected: string;
  flowSwitchToList: string;
  flowSwitchToFlow: string;
  flowListLabel: string;
  flowFlowLabel: string;
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
  flowEnabled: boolean;
  flowMode: boolean;
  onToggleFlowMode: () => void;
};

function isDeviceBusy(d: Device) {
  return isManualControlBlockedByAutomation(d);
}

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
  wsConnected,
  flowEnabled,
  flowMode,
  onToggleFlowMode
}: ControlRecordTopBarProps) {
  return (
    <div className='flex min-w-0 shrink-0 items-center gap-3 overflow-hidden border-b bg-background px-3 py-2'>
      <div className='h-5 w-px bg-border' />

      <div className='min-w-0 flex-1'>
        <p className='truncate text-sm font-semibold leading-tight'>{title}</p>
        <p className='text-[10px] text-muted-foreground'>{eyebrow}</p>
      </div>

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

      <div className='flex min-w-0 shrink items-center gap-1.5'>
        <div className='min-w-0 max-w-[min(240px,calc(100vw-16rem))]'>
          <Select
            value={deviceSelectValue}
            onValueChange={(v) => onDeviceChange(v || null)}
          >
            <SelectTrigger
              className={cn(
                'h-8 w-full min-w-0 max-w-full overflow-hidden text-xs',
                '[&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate [&_[data-slot=select-value]]:text-left'
              )}
            >
              <SelectValue placeholder={labels.selectPhonePlaceholder} />
            </SelectTrigger>
            <SelectContent className='max-w-[min(420px,calc(100vw-2rem))]'>
              {devices.map((d) => (
                <SelectItem
                  key={d.serial}
                  value={d.serial}
                  title={deviceSelectFullTitle(d)}
                  className='text-xs'
                >
                  <span className='inline-flex min-w-0 max-w-full items-center gap-1'>
                    <span className='min-w-0 truncate'>
                      {formatDeviceSelectLabel(d)}
                    </span>
                    {isDeviceBusy(d) ? (
                      <Badge
                        variant='outline'
                        className='h-4 shrink-0 border-amber-400/40 bg-amber-400/10 px-1 text-[9px] font-medium text-amber-700 dark:text-amber-300'
                      >
                        {labels.deviceCampaignBadge}
                      </Badge>
                    ) : null}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
            ? 'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400'
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

      <div className='h-5 w-px bg-border' />

      {flowEnabled ? (
        <Button
          size='sm'
          variant={flowMode ? 'default' : 'outline'}
          className='h-8 shrink-0 gap-1.5 text-xs'
          onClick={onToggleFlowMode}
          title={flowMode ? labels.flowSwitchToList : labels.flowSwitchToFlow}
        >
          {flowMode ? (
            <List className='size-3.5' />
          ) : (
            <GitBranch className='size-3.5' />
          )}
          {flowMode ? labels.flowListLabel : labels.flowFlowLabel}
        </Button>
      ) : null}
    </div>
  );
}
