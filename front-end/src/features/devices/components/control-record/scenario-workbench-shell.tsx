'use client';

import type { ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  Loader2,
  PanelRight,
  Smartphone,
  TriangleAlert
} from 'lucide-react';

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup
} from '@/components/ui/resizable';
import { cn } from '@/lib/utils';

type WorkbenchProblemState =
  | 'idle'
  | 'checking'
  | 'ready'
  | 'blocked'
  | 'warning';

type ScenarioWorkbenchProblem = {
  state: WorkbenchProblemState;
  title: string;
  description?: string;
};

type ScenarioWorkbenchShellProps = {
  hasSelectedDevice: boolean;
  showEditorPanel: boolean;
  hierarchyOpen: boolean;
  mode: 'build' | 'run' | 'inspect';
  phoneTitle: string;
  phoneMeta?: string;
  sequenceTitle: string;
  sequenceMeta: string;
  toolbar: ReactNode;
  hierarchy: ReactNode;
  phone: ReactNode;
  children: ReactNode;
  problem?: ScenarioWorkbenchProblem | null;
};

function modeLabel(mode: ScenarioWorkbenchShellProps['mode']): string {
  return mode;
}

function modeTone(mode: ScenarioWorkbenchShellProps['mode']): string {
  if (mode === 'run') {
    return 'border-sky-500/35 bg-sky-500/10 text-sky-800 dark:text-sky-200';
  }
  if (mode === 'inspect') {
    return 'border-amber-500/35 bg-amber-500/10 text-amber-800 dark:text-amber-200';
  }
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200';
}

function problemIcon(state: WorkbenchProblemState) {
  if (state === 'checking')
    return <Loader2 className='size-3.5 animate-spin' />;
  if (state === 'blocked') return <AlertCircle className='size-3.5' />;
  if (state === 'warning') return <TriangleAlert className='size-3.5' />;
  if (state === 'ready') return <CheckCircle2 className='size-3.5' />;
  return <CircleDot className='size-3.5' />;
}

function problemTone(state: WorkbenchProblemState): string {
  if (state === 'blocked') {
    return 'border-destructive/35 bg-destructive/10 text-destructive';
  }
  if (state === 'warning') {
    return 'border-amber-500/35 bg-amber-500/10 text-amber-800 dark:text-amber-200';
  }
  if (state === 'ready') {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200';
  }
  return 'border-border/70 bg-muted/30 text-muted-foreground';
}

export function ScenarioWorkbenchShell({
  hasSelectedDevice,
  showEditorPanel,
  hierarchyOpen,
  mode,
  phoneTitle,
  phoneMeta,
  sequenceTitle,
  sequenceMeta,
  toolbar,
  hierarchy,
  phone,
  children,
  problem
}: ScenarioWorkbenchShellProps) {
  const t = useTranslations('devicesControlRecord.view.workbench');
  const phoneDefaultSize = !showEditorPanel ? 100 : hierarchyOpen ? 48 : 30;
  const phoneMinSize = !showEditorPanel ? 100 : hierarchyOpen ? 44 : 28;
  const phoneMaxSize = !showEditorPanel ? 100 : hierarchyOpen ? 62 : 38;
  const sequenceDefaultSize = 100 - phoneDefaultSize;
  const sequenceMinSize = hierarchyOpen ? 38 : 44;

  return (
    <div
      className={cn(
        'flex min-h-0 flex-1 overflow-hidden max-md:hidden',
        !hasSelectedDevice && 'hidden'
      )}
    >
      <div className='flex min-h-0 min-w-0 flex-1 flex-col bg-background'>
        <div className='flex min-h-[44px] shrink-0 items-center gap-3 border-b border-border/60 bg-background px-3 py-1.5'>
          <div className='flex min-w-[240px] max-w-[38%] items-center gap-2'>
            <span
              className={cn(
                'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2 text-[11px] font-semibold',
                modeTone(mode)
              )}
            >
              <Smartphone className='size-3.5' />
              {t(`mode.${modeLabel(mode)}`)}
            </span>
            <div className='min-w-0'>
              <div className='truncate text-xs font-semibold text-foreground'>
                {phoneTitle}
              </div>
              {phoneMeta ? (
                <div className='truncate text-[10px] text-muted-foreground'>
                  {phoneMeta}
                </div>
              ) : null}
            </div>
          </div>
          <div className='min-w-0 flex-1'>{toolbar}</div>
        </div>

        <ResizablePanelGroup
          key={[
            showEditorPanel ? 'workbench-phone-editor' : 'workbench-phone',
            hierarchyOpen ? 'hierarchy-open' : 'hierarchy-closed'
          ].join(':')}
          direction='horizontal'
          className='min-h-0 min-w-0 flex-1'
        >
          <ResizablePanel
            id='control-record-phone-surface'
            order={1}
            defaultSize={phoneDefaultSize}
            minSize={phoneMinSize}
            maxSize={phoneMaxSize}
          >
            <section className='flex h-full min-w-0 overflow-hidden border-r border-border/60 bg-muted/10'>
              <div className='flex h-full shrink-0'>{hierarchy}</div>
              <div className='min-h-0 min-w-[260px] flex-1 overflow-hidden'>
                {phone}
              </div>
            </section>
          </ResizablePanel>

          {showEditorPanel ? (
            <>
              <ResizableHandle
                withHandle
                className='z-20 w-1 bg-border/70 hover:bg-primary/40 focus-visible:bg-primary/40'
              />
              <ResizablePanel
                id='control-record-sequence-workspace'
                order={2}
                defaultSize={sequenceDefaultSize}
                minSize={sequenceMinSize}
              >
                <section className='flex h-full min-w-0 flex-col overflow-hidden bg-background'>
                  <div className='flex h-10 shrink-0 items-center gap-2 border-b border-border/50 bg-background px-3'>
                    <PanelRight className='size-3.5 shrink-0 text-muted-foreground' />
                    <div className='min-w-0 flex-1'>
                      <div className='truncate text-xs font-semibold text-foreground'>
                        {sequenceTitle}
                      </div>
                      <div className='truncate text-[10px] text-muted-foreground'>
                        {sequenceMeta}
                      </div>
                    </div>
                  </div>
                  <div className='min-h-0 flex-1 overflow-hidden'>
                    {children}
                  </div>
                </section>
              </ResizablePanel>
            </>
          ) : null}
        </ResizablePanelGroup>

        <div
          className={cn(
            'flex min-h-[38px] shrink-0 items-center gap-2 border-t px-3 py-1.5 text-xs',
            problemTone(problem?.state ?? 'idle')
          )}
        >
          {problemIcon(problem?.state ?? 'idle')}
          <span className='shrink-0 font-semibold'>{t('problems')}</span>
          <span className='min-w-0 truncate'>
            {problem?.title ?? t('defaultProblemTitle')}
          </span>
          {problem?.description ? (
            <span className='hidden min-w-0 flex-1 truncate text-[11px] opacity-85 lg:inline'>
              {problem.description}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
