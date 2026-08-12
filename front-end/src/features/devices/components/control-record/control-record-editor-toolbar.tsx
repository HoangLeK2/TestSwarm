'use client';

import {
  AlertCircle,
  ChevronRight,
  Circle,
  Code2,
  Settings2,
  HelpCircle,
  GitBranch,
  List,
  Play,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Square
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
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
  flowSwitchToList: string;
  flowSwitchToFlow: string;
  flowListLabel: string;
  flowFlowLabel: string;
  settings: string;
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
  pageSummary?: string;
  pageSummaryWarning?: string;
  showRecovery: boolean;
  recoveryEnabled: boolean;
  onOpenRecovery: () => void;
  onOpenDeviceVars: () => void;
  deviceVarsEnabled: boolean;
  deviceVarsDisabled: boolean;
  onHelpClick?: () => void;
  flowEnabled: boolean;
  flowMode: boolean;
  onToggleFlowMode: () => void;
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
  pageSummary,
  pageSummaryWarning,
  showRecovery,
  recoveryEnabled,
  onOpenRecovery,
  onOpenDeviceVars,
  deviceVarsEnabled,
  deviceVarsDisabled,
  onHelpClick,
  flowEnabled,
  flowMode,
  onToggleFlowMode,
  labels
}: ControlRecordEditorToolbarProps) {
  return (
    <div className='flex shrink-0 items-center gap-1 border-b border-border/50 bg-background px-2 py-2'>
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
      <div className='flex min-w-0 flex-1 flex-nowrap items-center gap-1.5 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'>
        {flowEnabled ? (
          <Button
            size='sm'
            variant='ghost'
            className='h-7 shrink-0 gap-1.5 px-2 text-xs'
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
        {flowEnabled ? <div className='h-5 w-px shrink-0 bg-border' /> : null}
        {pollingXml ? (
          <RefreshCw size={12} className='animate-spin text-red-500/80' />
        ) : null}
        {pageSummary ? (
          <div
            className={cn(
              'flex h-7 max-w-[min(36rem,55vw)] shrink-0 items-center gap-1.5 rounded-md border px-2 text-xs',
              pageSummaryWarning
                ? 'border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200'
                : 'border-border/70 bg-muted/50 text-muted-foreground'
            )}
            title={
              pageSummaryWarning
                ? `${pageSummary} · ${pageSummaryWarning}`
                : pageSummary
            }
          >
            <List className='size-3.5 shrink-0' />
            <span className='truncate'>{pageSummary}</span>
          </div>
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
      </div>
      <div className='h-5 w-px shrink-0 bg-border' />
      <div className='flex shrink-0 items-center gap-1.5'>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size='sm'
              variant='outline'
              className={cn(
                'h-7 shrink-0 gap-1.5 px-2.5 text-xs',
                (variableCount > 0 || recoveryEnabled || deviceVarsEnabled) &&
                  'border-primary/40 bg-primary/5'
              )}
            >
              <Settings2 className='size-3.5' />
              {labels.settings}
              {variableCount > 0 ? (
                <span className='rounded-full bg-primary/15 px-1.5 text-[10px] font-bold text-primary'>
                  {variableCount}
                </span>
              ) : null}
              {recoveryEnabled ? (
                <span className='size-1.5 rounded-full bg-amber-500' />
              ) : null}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className='w-72'>
            <DropdownMenuLabel>{labels.settings}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className='gap-2'
              onClick={onOpenJson}
              disabled={!hasSteps}
            >
              <Code2 className='size-4' />
              <div className='min-w-0'>
                <p>{labels.jsonTooltip}</p>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem className='gap-2' onClick={onOpenVariables}>
              <SlidersHorizontal className='size-4' />
              <div className='min-w-0 flex-1'>
                <p>{labels.variables}</p>
                <p className='truncate text-[10px] text-muted-foreground'>
                  {labels.variablesTooltip}
                </p>
              </div>
              {variableCount > 0 ? (
                <span className='rounded-full bg-primary/15 px-1.5 text-[10px] font-bold text-primary'>
                  {variableCount}
                </span>
              ) : null}
            </DropdownMenuItem>
            {showRecovery ? (
              <DropdownMenuItem className='gap-2' onClick={onOpenRecovery}>
                <AlertCircle className='size-4' />
                <div className='min-w-0 flex-1'>
                  <p>{labels.recoveryTitle}</p>
                  <p className='truncate text-[10px] text-muted-foreground'>
                    {labels.recoveryTooltip}
                  </p>
                </div>
                {recoveryEnabled ? (
                  <span className='rounded-full bg-amber-500/15 px-1.5 text-[10px] font-bold text-amber-700 dark:text-amber-300'>
                    {labels.recoveryEnabledBadge}
                  </span>
                ) : null}
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuItem
              className='gap-2'
              onClick={onOpenDeviceVars}
              disabled={deviceVarsDisabled}
            >
              <SlidersHorizontal className='size-4' />
              <div className='min-w-0 flex-1'>
                <p>{labels.deviceVars}</p>
                <p className='truncate text-[10px] text-muted-foreground'>
                  {labels.deviceVarsTooltip}
                </p>
              </div>
              {deviceVarsEnabled ? (
                <span className='size-1.5 rounded-full bg-emerald-500' />
              ) : null}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          size='sm'
          variant='default'
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
