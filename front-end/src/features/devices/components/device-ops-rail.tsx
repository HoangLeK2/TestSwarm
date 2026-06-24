'use client';

import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { Trash2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { SCENARIO_VAR_TOKENS } from '@/features/campaigns/i18n/scenario-var-tokens';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import {
  createDefaultStep,
  type FlowStep
} from '@/features/campaigns/components/scenario-steps/types';
import {
  AppLifecycleStepFields,
  StepPanelHint
} from '@/features/campaigns/components/flow-editor/step-panel-primitives';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import {
  DeviceShellTerminal,
  type DeviceShellResult
} from './device-shell-terminal';

export type { DeviceShellResult };

export type DeviceOpsConfig = {
  disabled?: boolean;
  defaultPackage?: string;
  onRunStep: (step: FlowStep) => Promise<void>;
  onRunShell?: (cmd: string) => Promise<DeviceShellResult>;
  onInstallApk: (url: string) => void;
};

type OpKind = 'adb_shell' | 'install_apk' | 'clear_app';

const RAIL_OPS: OpKind[] = ['adb_shell', 'install_apk', 'clear_app'];

const RAIL_HINT_KEY: Record<
  OpKind,
  'adb_shellHint' | 'install_apkHint' | 'clear_appHint'
> = {
  adb_shell: 'adb_shellHint',
  install_apk: 'install_apkHint',
  clear_app: 'clear_appHint'
};

function RailIconButton({
  label,
  hint,
  onClick,
  disabled,
  children
}: {
  label: string;
  hint?: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type='button'
          aria-label={label}
          disabled={disabled}
          onClick={onClick}
          className={cn(
            'mx-auto flex size-9 shrink-0 items-center justify-center rounded-full transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900',
            disabled
              ? 'cursor-not-allowed text-zinc-600'
              : 'text-zinc-300 hover:bg-white/15 hover:text-white'
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side='left' className='text-xs'>
        {hint ?? label}
      </TooltipContent>
    </Tooltip>
  );
}

export function packageFromCurrentApp(current?: string | null): string {
  if (!current) return '';
  const s = current.trim();
  if (!s) return '';
  if (s.includes('/')) return s.split('/')[0] ?? s;
  return s;
}

export function DeviceOpsRailSection({
  config,
  iconClass = 'size-[18px] shrink-0 stroke-[2.25]'
}: {
  config?: DeviceOpsConfig;
  iconClass?: string;
}) {
  const tRail = useTranslations('devicesControlRecord.deviceOps.rail');
  const tApp = useTranslations('campaignsFeature.stepEditor.appLifecycle');
  const tAdb = useTranslations('campaignsFeature.stepEditor.adbShell');
  const tRun = useTranslations('devicesControlRecord.deviceOps');

  const [open, setOpen] = useState<OpKind | null>(null);
  const [draft, setDraft] = useState<FlowStep | null>(null);
  const [running, setRunning] = useState(false);
  const shellApiRef = useRef<{ clear: () => void } | null>(null);

  const defaultPkg = config?.defaultPackage?.trim() ?? '';

  const openOp = useCallback(
    (kind: OpKind) => {
      if (!config || config.disabled) return;
      const step = createDefaultStep(kind);
      if (kind === 'clear_app' && defaultPkg) {
        (step as FlowStep).package = defaultPkg;
      }
      setDraft(step);
      setOpen(kind);
    },
    [config, defaultPkg]
  );

  const updateDraft = useCallback((fields: Partial<FlowStep>) => {
    setDraft((prev) => (prev ? { ...prev, ...fields } : prev));
  }, []);

  const close = useCallback(() => {
    setOpen(null);
    setDraft(null);
    setRunning(false);
    shellApiRef.current = null;
  }, []);

  const runShellCommand = useCallback(
    async (cmd: string): Promise<DeviceShellResult | void> => {
      if (!config || !draft || draft.type !== 'adb_shell') return;
      if (config.disabled) return;

      updateDraft({ command: cmd });

      if (config.onRunShell) {
        return config.onRunShell(cmd);
      }

      await config.onRunStep({ ...draft, command: cmd });
      return { ok: true, cmd, note: tRun('shellStepSubmitted') };
    },
    [config, draft, tRun, updateDraft]
  );

  const runDraft = useCallback(async () => {
    if (!config || !draft) return;
    if (draft.type === 'install_apk') {
      const url = (draft.url ?? '').trim();
      if (!url) {
        toast.warning(tRun('installUrlRequired'));
        return;
      }
      config.onInstallApk(url);
      close();
      return;
    }
    if (draft.type === 'adb_shell') {
      const cmd = (draft.command ?? draft.cmd ?? '').trim();
      if (!cmd) {
        toast.warning(tRun('shellRequired'));
        return;
      }
    }
    if (draft.type === 'clear_app' && !(draft.package ?? '').trim()) {
      toast.warning(tRun('packageRequired'));
      return;
    }
    setRunning(true);
    try {
      await config.onRunStep(draft);
      close();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setRunning(false);
    }
  }, [config, draft, close, tRun]);

  const labels = useMemo(
    () =>
      Object.fromEntries(
        RAIL_OPS.map((kind) => [
          kind,
          { label: tRail(kind), hint: tRail(RAIL_HINT_KEY[kind]) }
        ])
      ) as Record<OpKind, { label: string; hint: string }>,
    [tRail]
  );

  if (!config) return null;

  return (
    <>
      {RAIL_OPS.map((kind) => (
        <RailIconButton
          key={kind}
          label={labels[kind].label}
          hint={labels[kind].hint}
          disabled={config.disabled}
          onClick={() => openOp(kind)}
        >
          <StepIcon
            type={kind}
            size={18}
            className={cn(iconClass, 'text-zinc-100')}
          />
        </RailIconButton>
      ))}

      <Dialog
        open={open != null}
        onOpenChange={(v) => {
          if (!v) close();
        }}
      >
        <DialogContent
          className={cn(
            open === 'adb_shell'
              ? '!grid !h-[min(88dvh,820px)] !w-[min(96vw,960px)] !max-w-[960px] grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden'
              : 'max-w-md sm:max-w-md'
          )}
        >
          {draft && open ? (
            <>
              <DialogHeader className='shrink-0'>
                <DialogTitle
                  className={cn(
                    'flex items-center gap-2',
                    open === 'adb_shell' ? 'text-lg' : 'text-base'
                  )}
                >
                  <StepIcon type={open} size={open === 'adb_shell' ? 20 : 18} />
                  {labels[open].label}
                </DialogTitle>
              </DialogHeader>

              {open === 'adb_shell' && draft.type === 'adb_shell' ? (
                <div className='grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-2'>
                  <StepPanelHint>{tAdb('hint')}</StepPanelHint>
                  <DeviceShellTerminal
                    disabled={running || config.disabled}
                    onRunCommand={runShellCommand}
                    onReady={(api) => {
                      shellApiRef.current = api;
                    }}
                  />
                  <div className='flex shrink-0 items-center justify-between gap-2 border-t border-border/40 pt-2 text-[11px] text-muted-foreground'>
                    <span>{tRun('shellShortcuts')}</span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          className='h-8 gap-1.5'
                          onClick={() => shellApiRef.current?.clear()}
                        >
                          <Trash2 className='size-3.5' aria-hidden />
                          {tRun('clear')}
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent className='text-xs'>
                        {tRun('clear')}
                      </TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              ) : null}

              {open === 'install_apk' && draft.type === 'install_apk' ? (
                <div className='space-y-2'>
                  <p className='text-[12px] text-muted-foreground'>
                    {tApp('installApkHint', { varToken: SCENARIO_VAR_TOKENS.VAR })}
                  </p>
                  <Input
                    placeholder={tApp('installApkUrlPlaceholder')}
                    value={draft.url ?? ''}
                    onChange={(e) => updateDraft({ url: e.target.value })}
                    className='h-8 font-mono text-xs'
                  />
                </div>
              ) : null}

              {open === 'clear_app' && draft.type === 'clear_app' ? (
                <AppLifecycleStepFields
                  step={draft}
                  update={updateDraft}
                  tApp={tApp}
                />
              ) : null}

              {open !== 'adb_shell' ? (
                <DialogFooter className='gap-2 sm:gap-2'>
                  <Button type='button' variant='outline' onClick={close}>
                    {tRun('cancel')}
                  </Button>
                  <Button
                    type='button'
                    disabled={running || config.disabled}
                    onClick={() => void runDraft()}
                  >
                    {running ? tRun('running') : tRun('run')}
                  </Button>
                </DialogFooter>
              ) : null}
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
