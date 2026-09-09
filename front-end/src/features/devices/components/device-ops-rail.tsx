'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode
} from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import {
  IconApps,
  IconBrandFacebookFilled,
  IconBrandGoogleFilled,
  IconBrandInstagramFilled,
  IconBrandThreads,
  IconBrandTiktokFilled
} from '@tabler/icons-react';
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { farmApi } from '@/lib/farm-api';
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

type FacebookAppInstallOut = {
  release: {
    version_name: string;
    version_code?: string | null;
  };
};

type FacebookAppReleaseOut = {
  version_name: string;
  version_code?: string | null;
};

export type DeviceOpsConfig = {
  disabled?: boolean;
  defaultPackage?: string;
  onRunStep: (step: FlowStep) => Promise<void>;
  onRunShell?: (cmd: string) => Promise<DeviceShellResult>;
  onInstallStandardFacebookApk?: () => Promise<FacebookAppInstallOut>;
};

type OpKind = 'adb_shell' | 'install_apk' | 'clear_app';
type QuickLaunchKey =
  | 'facebook'
  | 'tiktok'
  | 'google'
  | 'instagram'
  | 'threads';

const RAIL_OPS: OpKind[] = ['adb_shell', 'install_apk', 'clear_app'];
const QUICK_LAUNCH_APPS: Array<{
  key: QuickLaunchKey;
  packageName: string;
  packageFallbacks?: string[];
  Icon: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
}> = [
  {
    key: 'facebook',
    packageName: 'com.facebook.katana',
    packageFallbacks: ['com.facebook.lite'],
    Icon: IconBrandFacebookFilled
  },
  {
    key: 'tiktok',
    packageName: 'com.ss.android.ugc.trill',
    packageFallbacks: [
      'com.zhiliaoapp.musically',
      'com.zhiliaoapp.musically.go',
      'com.ss.android.ugc.aweme'
    ],
    Icon: IconBrandTiktokFilled
  },
  {
    key: 'google',
    packageName: 'com.google.android.googlequicksearchbox',
    packageFallbacks: [
      'com.android.chrome',
      'com.google.android.apps.searchlite'
    ],
    Icon: IconBrandGoogleFilled
  },
  {
    key: 'instagram',
    packageName: 'com.instagram.android',
    packageFallbacks: ['com.instagram.lite'],
    Icon: IconBrandInstagramFilled
  },
  {
    key: 'threads',
    packageName: 'com.instagram.barcelona',
    Icon: IconBrandThreads
  }
];

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
  const [quickLaunching, setQuickLaunching] = useState<QuickLaunchKey | null>(
    null
  );
  const [loadingFacebookApk, setLoadingFacebookApk] = useState(false);
  const [loadingFacebookRelease, setLoadingFacebookRelease] = useState(false);
  const [facebookRelease, setFacebookRelease] =
    useState<FacebookAppReleaseOut | null>(null);
  const [showManualApkUrl, setShowManualApkUrl] = useState(false);
  const shellApiRef = useRef<{ clear: () => void } | null>(null);

  const defaultPkg = config?.defaultPackage?.trim() ?? '';

  const openOp = useCallback(
    (kind: OpKind) => {
      if (!config || config.disabled) return;
      const step = createDefaultStep(kind);
      if (kind === 'clear_app' && defaultPkg) {
        (step as FlowStep).package = defaultPkg;
      }
      setShowManualApkUrl(false);
      setFacebookRelease(null);
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
    setShowManualApkUrl(false);
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

  useEffect(() => {
    if (open !== 'install_apk') return;
    let cancelled = false;
    setLoadingFacebookRelease(true);
    farmApi
      .get<FacebookAppReleaseOut>('/platform-apps/facebook/current')
      .then(({ data }) => {
        if (!cancelled) setFacebookRelease(data);
      })
      .catch(() => {
        if (!cancelled) setFacebookRelease(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingFacebookRelease(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const runDraft = useCallback(async () => {
    if (!config || !draft) return;
    if (draft.type === 'install_apk') {
      const url = (draft.url ?? '').trim();
      if (!url) {
        toast.warning(tRun('installUrlRequired'));
        return;
      }
      setRunning(true);
      try {
        await config.onRunStep({ ...draft, url, timeout: draft.timeout ?? 600 });
        toast.success(tRun('installApkSubmitted'));
        close();
      } catch (e) {
        toast.error(String(e));
      } finally {
        setRunning(false);
      }
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

  const fillStandardFacebookApk = useCallback(async () => {
    if (!config || !draft || draft.type !== 'install_apk') return;
    if (!config.onInstallStandardFacebookApk) {
      toast.error(tRun('standardFacebookApkUnavailable'));
      return;
    }
    setLoadingFacebookApk(true);
    try {
      const data = await config.onInstallStandardFacebookApk();
      toast.success(tRun('installApkSubmitted'));
      toast.success(
        tRun('facebookApkSelected', {
          version: data.release.version_name
        })
      );
      close();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setLoadingFacebookApk(false);
    }
  }, [close, config, draft, tRun]);

  const launchQuickApp = useCallback(
    async (app: (typeof QUICK_LAUNCH_APPS)[number]) => {
      if (!config || config.disabled || quickLaunching) return;
      setQuickLaunching(app.key);
      try {
        await config.onRunStep({
          type: 'launch_app',
          package: app.packageName,
          package_fallbacks: app.packageFallbacks ?? [],
          wait_after: 1
        });
        toast.success(tRail('quickLaunchSubmitted', { app: tRail(app.key) }));
      } catch (e) {
        toast.error(String(e));
      } finally {
        setQuickLaunching(null);
      }
    },
    [config, quickLaunching, tRail]
  );

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
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <button
                type='button'
                aria-label={tRail('quickLaunch')}
                disabled={config.disabled || quickLaunching != null}
                className={cn(
                  'mx-auto flex size-9 shrink-0 items-center justify-center rounded-full transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900',
                  config.disabled || quickLaunching != null
                    ? 'cursor-not-allowed text-zinc-600'
                    : 'text-zinc-300 hover:bg-white/15 hover:text-white'
                )}
              >
                <IconApps className={iconClass} aria-hidden />
              </button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent side='left' className='text-xs'>
            {tRail('quickLaunchHint')}
          </TooltipContent>
        </Tooltip>
        <DropdownMenuContent side='left' align='start' className='w-48'>
          {QUICK_LAUNCH_APPS.map((app) => {
            const Icon = app.Icon;
            return (
              <DropdownMenuItem
                key={app.key}
                disabled={config.disabled || quickLaunching != null}
                onSelect={() => {
                  void launchQuickApp(app);
                }}
                className='gap-2.5'
              >
                <Icon
                  className={cn(
                    'size-4.5 shrink-0',
                    quickLaunching === app.key
                      ? 'text-primary'
                      : 'text-muted-foreground'
                  )}
                  aria-hidden
                />
                <span>{tRail(app.key)}</span>
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>

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
                <div className='space-y-3'>
                  <p className='text-[12px] text-muted-foreground'>
                    {tRun('standardFacebookApkHint')}
                  </p>
                  <div className='grid gap-2'>
                    <button
                      type='button'
                      className={cn(
                        'flex w-full items-center gap-3 rounded-md border bg-background p-3 text-left transition-colors hover:bg-muted/50',
                        showManualApkUrl && 'border-primary bg-primary/5'
                      )}
                      onClick={() => setShowManualApkUrl((value) => !value)}
                    >
                      <span className='flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted/40 font-mono text-xs font-semibold text-muted-foreground'>
                        1
                      </span>
                      <span className='min-w-0'>
                        <span className='block text-sm font-medium'>
                          {tRun('manualApkTitle')}
                        </span>
                        <span className='mt-0.5 block text-xs text-muted-foreground'>
                          {tRun('manualApkDescription')}
                        </span>
                      </span>
                    </button>
                    <button
                      type='button'
                      className='flex w-full items-center gap-3 rounded-md border bg-background p-3 text-left transition-colors hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-60'
                      disabled={
                        loadingFacebookApk ||
                        loadingFacebookRelease ||
                        !facebookRelease ||
                        config?.disabled
                      }
                      onClick={() => void fillStandardFacebookApk()}
                    >
                      <span className='flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted/40 text-blue-600'>
                        {loadingFacebookApk || loadingFacebookRelease ? (
                          <Loader2 className='size-4 animate-spin' />
                        ) : (
                          <IconBrandFacebookFilled className='size-5' aria-hidden />
                        )}
                      </span>
                      <span className='min-w-0'>
                        <span className='block truncate text-sm font-medium'>
                          {facebookRelease
                            ? tRun('standardFacebookApkOption', {
                                version: facebookRelease.version_name
                              })
                            : tRun('standardFacebookApkMissing')}
                        </span>
                        <span className='mt-0.5 block text-xs text-muted-foreground'>
                          {tRun('standardFacebookApkDescription')}
                        </span>
                      </span>
                    </button>
                  </div>
                  {showManualApkUrl ? (
                    <div className='rounded-md border bg-muted/30 p-3'>
                      <div className='space-y-2'>
                        <p className='text-[12px] text-muted-foreground'>
                          {tApp('installApkHint', {
                            varToken: SCENARIO_VAR_TOKENS.VAR
                          })}
                        </p>
                        <Input
                          placeholder={tApp('installApkUrlPlaceholder')}
                          value={draft.url ?? ''}
                          onChange={(e) => updateDraft({ url: e.target.value })}
                          className='h-8 font-mono text-xs'
                        />
                      </div>
                    </div>
                  ) : null}
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
                  {open !== 'install_apk' || showManualApkUrl ? (
                    <Button
                      type='button'
                      disabled={running || config.disabled}
                      onClick={() => void runDraft()}
                    >
                      {running ? tRun('running') : tRun('run')}
                    </Button>
                  ) : null}
                </DialogFooter>
              ) : null}
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
