'use client';

import {
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Keyboard,
  MousePointerClick,
  Timer
} from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

import { XmlTreeViewer } from './xml-tree-viewer';

type SelectorStepType =
  | 'tap_selector'
  | 'long_tap_selector'
  | 'wait_element'
  | 'assert_element'
  | 'input_selector';

type TreeNodeSelectPayload = {
  bounds: [number, number, number, number] | null;
  by: string;
  value: string;
  nodeId: number;
};

type ControlRecordHierarchyPanelProps = {
  open: boolean;
  hiddenForMultiFollowers: boolean;
  safeHierarchy: boolean;
  xml: string;
  loading: boolean;
  deviceActive: boolean;
  wsConnected: boolean;
  onNodeSelect: (payload: TreeNodeSelectPayload) => void;
  selectedNodeId: number | null;
  onRefresh: () => void;
  autoRefresh: boolean;
  onAutoRefreshChange: (next: boolean) => void;
  selectorBy: string;
  selectorValue: string;
  onTapSelector: () => void;
  onAddStepFromSelector: (stepType: SelectorStepType) => void;
  canExecuteDevice: boolean;
  hasSelectedDevice: boolean;
  safeReadOnly: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  selectorBarHint: string;
};

export function ControlRecordHierarchyPanel({
  open,
  hiddenForMultiFollowers,
  safeHierarchy,
  xml,
  loading,
  deviceActive,
  wsConnected,
  onNodeSelect,
  selectedNodeId,
  onRefresh,
  autoRefresh,
  onAutoRefreshChange,
  selectorBy,
  selectorValue,
  onTapSelector,
  onAddStepFromSelector,
  canExecuteDevice,
  hasSelectedDevice,
  safeReadOnly,
  collapsed,
  onToggleCollapsed,
  selectorBarHint
}: ControlRecordHierarchyPanelProps) {
  const t = useTranslations('devicesControlRecord.view');

  return (
    <>
      <div
        className={cn(
          'flex shrink-0 flex-col border-r border-border/60 bg-muted/10 transition-all duration-200',
          open ? 'w-[280px]' : 'w-0 overflow-hidden'
        )}
      >
        <div className='min-h-0 flex-1 overflow-hidden'>
          {!safeHierarchy ? (
            <div className='p-3 text-[11px] text-muted-foreground'>
              {t('safeModeNoHierarchy')}
            </div>
          ) : (
            <XmlTreeViewer
              xml={xml}
              loading={loading}
              deviceActive={deviceActive}
              wsConnected={wsConnected}
              onNodeSelect={onNodeSelect}
              selectedNodeId={selectedNodeId}
              onRefresh={onRefresh}
              autoRefresh={autoRefresh}
              onAutoRefreshChange={onAutoRefreshChange}
            />
          )}
        </div>

        <div
          className={cn(
            'shrink-0 border-t border-border/60 px-2.5 py-2',
            selectorValue ? 'bg-primary/5' : 'bg-muted/30'
          )}
        >
          {selectorValue ? (
            <>
              <div className='flex items-center gap-1.5 pb-1.5'>
                <span className='min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground'>
                  <span className='font-bold text-primary'>[{selectorBy}]</span>{' '}
                  {selectorValue}
                </span>
                <Button
                  size='sm'
                  variant='secondary'
                  className='h-5 shrink-0 px-1.5 text-[9px]'
                  onClick={onTapSelector}
                  disabled={!hasSelectedDevice || !canExecuteDevice}
                  title={
                    !canExecuteDevice && safeReadOnly
                      ? t('safeModeReadOnly')
                      : undefined
                  }
                >
                  {t('tapShort')}
                </Button>
              </div>
              {!canExecuteDevice ? (
                <p className='text-[10px] italic text-muted-foreground'>
                  {safeReadOnly
                    ? t('safeModeNoControlSteps')
                    : t('noControlPermission')}
                </p>
              ) : (
                <div className='flex flex-wrap gap-1'>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => onAddStepFromSelector('tap_selector')}
                        className='flex items-center gap-0.5 rounded bg-blue-500/10 px-1.5 py-0.5 text-[9px] font-medium text-blue-700 hover:bg-blue-500/20 dark:text-blue-400'
                      >
                        <MousePointerClick className='size-2.5' />{' '}
                        {t('tapShort')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>
                      {t('addStepTapSelector')}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() =>
                          onAddStepFromSelector('long_tap_selector')
                        }
                        className='flex items-center gap-0.5 rounded bg-purple-500/10 px-1.5 py-0.5 text-[9px] font-medium text-purple-700 hover:bg-purple-500/20 dark:text-purple-400'
                      >
                        <MousePointerClick className='size-2.5' />{' '}
                        {t('longTapShort')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>
                      {t('addStepLongTapSelector')}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => onAddStepFromSelector('wait_element')}
                        className='flex items-center gap-0.5 rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-700 hover:bg-amber-500/20 dark:text-amber-400'
                      >
                        <Timer className='size-2.5' /> {t('waitShort')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>
                      {t('addStepWaitElement')}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => onAddStepFromSelector('assert_element')}
                        className='flex items-center gap-0.5 rounded bg-green-500/10 px-1.5 py-0.5 text-[9px] font-medium text-green-700 hover:bg-green-500/20 dark:text-green-400'
                      >
                        <CheckSquare className='size-2.5' /> {t('assertShort')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>
                      {t('addStepAssertElement')}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => onAddStepFromSelector('input_selector')}
                        className='flex items-center gap-0.5 rounded bg-orange-500/10 px-1.5 py-0.5 text-[9px] font-medium text-orange-700 hover:bg-orange-500/20 dark:text-orange-400'
                      >
                        <Keyboard className='size-2.5' /> {t('inputShort')}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>
                      {t('addStepInputSelector')}
                    </TooltipContent>
                  </Tooltip>
                </div>
              )}
            </>
          ) : (
            <p className='text-[10px] text-muted-foreground'>
              {selectorBarHint}
            </p>
          )}
        </div>
      </div>

      {!hiddenForMultiFollowers ? (
        <button
          type='button'
          onClick={onToggleCollapsed}
          className={cn(
            'relative z-10 flex shrink-0 items-center justify-center border-r border-border/40 bg-muted/20 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
            collapsed ? 'w-7' : 'w-4'
          )}
          title={collapsed ? t('expandHierarchy') : t('collapseHierarchy')}
          aria-label={collapsed ? t('expandHierarchy') : t('collapseHierarchy')}
        >
          {collapsed ? (
            <ChevronRight className='size-3' />
          ) : (
            <ChevronLeft className='size-3' />
          )}
        </button>
      ) : null}
    </>
  );
}
