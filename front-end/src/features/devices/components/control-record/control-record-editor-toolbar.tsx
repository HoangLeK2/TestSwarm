'use client';

import {
  AlertCircle,
  ChevronRight,
  Circle,
  Code2,
  HelpCircle,
  Play,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Square
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

type ControlRecordEditorToolbarLabels = {
  closePickerTitle: string;
  startRecording: string;
  stopRecording: string;
  tryRun: string;
  busyTitle: string;
  jsonTooltip: string;
  variables: string;
  variablesTooltip: string;
  recoveryTitle: string;
  recoveryEnabledBadge: string;
  recoveryTooltip: string;
  deviceVars: string;
  deviceVarsTooltip: string;
  helpTooltip: string;
};

type ControlRecordEditorToolbarProps = {
  showClosePicker: boolean;
  onClosePicker: () => void;
  pollingXml: boolean;
  recording: boolean;
  onToggleRecording: () => void;
  hasSelectedDevice: boolean;
  selectedDeviceBusy: boolean;
  onOpenPlayer: () => void;
  onOpenJson: () => void;
  hasSteps: boolean;
  onSave: () => void;
  saveDisabled: boolean;
  saveLabel: string;
  onOpenVariables: () => void;
  variableCount: number;
  showRecovery: boolean;
  recoveryEnabled: boolean;
  onOpenRecovery: () => void;
  onOpenDeviceVars: () => void;
  deviceVarsEnabled: boolean;
  deviceVarsDisabled: boolean;
  onHelpClick?: () => void;
  labels: ControlRecordEditorToolbarLabels;
};

export function ControlRecordEditorToolbar({
  showClosePicker,
  onClosePicker,
  pollingXml,
  recording,
  onToggleRecording,
  hasSelectedDevice,
  selectedDeviceBusy,
  onOpenPlayer,
  onOpenJson,
  hasSteps,
  onSave,
  saveDisabled,
  saveLabel,
  onOpenVariables,
  variableCount,
  showRecovery,
  recoveryEnabled,
  onOpenRecovery,
  onOpenDeviceVars,
  deviceVarsEnabled,
  deviceVarsDisabled,
  onHelpClick,
  labels
}: ControlRecordEditorToolbarProps) {
  return (
    <div className='flex shrink-0 items-center gap-1 border-b border-border/40 bg-muted/20 px-2 py-2'>
      {showClosePicker ? (
        <Button
          type='button'
          size='sm'
          variant='ghost'
          className='h-7 shrink-0 gap-1 px-2 text-xs text-muted-foreground'
          onClick={onClosePicker}
          title={labels.closePickerTitle}
        >
          <ChevronRight className='size-3.5' />
        </Button>
      ) : null}
      <div className='flex min-w-0 max-w-full flex-1 flex-nowrap items-center gap-1.5 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'>
        {pollingXml ? (
          <RefreshCw size={12} className='animate-spin text-red-500/80' />
        ) : null}
        <Button
          size='sm'
          variant={recording ? 'destructive' : 'default'}
          className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
          onClick={onToggleRecording}
          disabled={!hasSelectedDevice}
        >
          {recording ? (
            <Square className='size-3.5' />
          ) : (
            <Circle className='size-3.5 fill-current' />
          )}
          {recording ? labels.stopRecording : labels.startRecording}
        </Button>
        <Button
          size='sm'
          variant='outline'
          className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
          onClick={onOpenPlayer}
          disabled={!hasSelectedDevice || selectedDeviceBusy}
          title={
            hasSelectedDevice && selectedDeviceBusy
              ? labels.busyTitle
              : undefined
          }
        >
          <Play className='size-3.5' />
          {labels.tryRun}
        </Button>
        <Tooltip delayDuration={300}>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant='ghost'
              className='h-7 w-7 shrink-0 p-0'
              onClick={onOpenJson}
              disabled={!hasSteps}
            >
              <Code2 className='size-3.5' />
            </Button>
          </TooltipTrigger>
          <TooltipContent side='bottom' className='text-xs'>
            {labels.jsonTooltip}
          </TooltipContent>
        </Tooltip>
        <Button
          size='sm'
          variant='outline'
          className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
          onClick={onSave}
          disabled={saveDisabled}
        >
          <Save className='size-3.5' />
          {saveLabel}
        </Button>
        <Tooltip delayDuration={400}>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant='outline'
              onClick={onOpenVariables}
              className={cn(
                'h-7 shrink-0 gap-1.5 px-2.5 text-xs',
                variableCount > 0 &&
                  'border-primary/40 bg-primary/10 text-primary hover:bg-primary/20'
              )}
            >
              <SlidersHorizontal className='size-3.5' />
              {labels.variables}
              {variableCount > 0 ? (
                <span className='rounded-full bg-primary/20 px-1.5 text-[10px] font-bold'>
                  {variableCount}
                </span>
              ) : null}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='bottom' className='text-xs'>
            {labels.variablesTooltip}
          </TooltipContent>
        </Tooltip>
        {showRecovery ? (
          <Tooltip delayDuration={400}>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                onClick={onOpenRecovery}
                className={cn(
                  'h-7 shrink-0 gap-1.5 px-2.5 text-xs',
                  recoveryEnabled &&
                    'border-amber-500/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-300'
                )}
              >
                <AlertCircle className='size-3.5' />
                {labels.recoveryTitle}
                {recoveryEnabled ? (
                  <span className='rounded-full bg-amber-500/20 px-1.5 text-[10px] font-bold'>
                    {labels.recoveryEnabledBadge}
                  </span>
                ) : null}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='bottom' className='max-w-xs text-xs'>
              {labels.recoveryTooltip}
            </TooltipContent>
          </Tooltip>
        ) : null}
        <Tooltip delayDuration={400}>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant='outline'
              onClick={onOpenDeviceVars}
              disabled={deviceVarsDisabled}
              className={cn(
                'h-7 shrink-0 gap-1.5 px-2.5 text-xs',
                deviceVarsEnabled
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-300'
                  : ''
              )}
            >
              <SlidersHorizontal className='size-3.5' />
              {labels.deviceVars}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='bottom' className='text-xs'>
            {labels.deviceVarsTooltip}
          </TooltipContent>
        </Tooltip>
        <Tooltip delayDuration={400}>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant='ghost'
              className='h-7 w-7 shrink-0 p-0'
              onClick={onHelpClick}
            >
              <HelpCircle className='size-3.5' />
            </Button>
          </TooltipTrigger>
          <TooltipContent side='bottom' className='max-w-xs text-xs'>
            {labels.helpTooltip}
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
