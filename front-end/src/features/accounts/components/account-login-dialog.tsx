'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  LogIn,
  Loader2,
  Smartphone,
  XCircle
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useDevices } from '@/features/devices/hooks/use-devices';
import type { DeviceOut } from '@/features/devices/services/manage-api';
import {
  cancelPreviewStream,
  previewScenarioStream
} from '@/features/devices/services/api';
import {
  deviceFsmStateOf,
  isDeviceFsmDispatchable
} from '@/features/devices/lib/device-fsm';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { useAccountDevices } from '../hooks/use-accounts';
import type { AccountOut } from '../services/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

/** A login scenario declares itself with this tag, not with its display name. */
const LOGIN_TEMPLATE_TAG = 'login';

function hasTag(tags: string | null | undefined, tag: string): boolean {
  return (tags ?? '')
    .split(',')
    .map((t) => t.trim().toLowerCase())
    .includes(tag);
}

function deviceLabel(d: Pick<DeviceOut, 'serial' | 'name'>) {
  return d.name?.trim() || d.serial || '—';
}

type StepLine = { index: number; type: string; ok: boolean; message: string };

/**
 * Session-gate refusals that are an operator problem, not a bug. The gate
 * refuses to log in when the phone is already showing a signed-in Facebook it
 * cannot attribute to this account — right call, useless message. Both codes
 * mean the same thing to whoever clicked the button: log the phone out first.
 */
const GATE_HINT_REASONS = [
  'facebook_session_account_mismatch',
  'facebook_ready_without_matching_provenance'
];

export function AccountLoginDialog({
  account,
  canUpdate
}: {
  account: AccountOut;
  canUpdate: boolean;
}) {
  const t = useTranslations('accountsFeature.loginDialog');
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [running, setRunning] = useState(false);
  const [lines, setLines] = useState<StepLine[]>([]);
  const [outcome, setOutcome] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  /** Serial + trace of the run in flight, so a close can cancel it server-side. */
  const runRef = useRef<{ serial: string; traceId: string | null } | null>(
    null
  );

  const { data: links = [], isLoading: loadingLinks } = useAccountDevices(
    open ? account.id : ''
  );
  const { data: allDevices = [] } = useDevices();
  const { data: templates = [], isLoading: loadingTemplates } =
    useScenarioTemplates(
      { category: account.platform, tags: LOGIN_TEMPLATE_TAG },
      { enabled: open }
    );

  const loginTemplate = useMemo(
    () => templates.find((tpl) => hasTag(tpl.tags, LOGIN_TEMPLATE_TAG)) ?? null,
    [templates]
  );

  /** Only phones this account is actually attached to may run its login. */
  const linkedDevices = useMemo(
    () =>
      links
        .map((link) => ({
          link,
          device: allDevices.find((d) => d.id === link.device_id)
        }))
        .filter(
          (row): row is { link: (typeof links)[number]; device: DeviceOut } =>
            row.device !== undefined
        ),
    [links, allDevices]
  );

  // Preselect the primary link, or the only one. Two non-primary phones stay
  // unselected on purpose — picking one for the operator would be a guess.
  useEffect(() => {
    if (!open || selectedDeviceId) return;
    const primary = linkedDevices.find((row) => row.link.is_primary);
    const pick =
      primary ?? (linkedDevices.length === 1 ? linkedDevices[0] : null);
    if (pick) setSelectedDeviceId(pick.device.id);
  }, [open, selectedDeviceId, linkedDevices]);

  // Closing the dialog must stop the phone, not just stop watching it. Dropping
  // the SSE socket alone leaves the scenario driving a real login until the
  // server notices the disconnect; the explicit cancel is what ends it now.
  useEffect(() => {
    if (open) return;
    abortRef.current?.abort();
    abortRef.current = null;
    const inflight = runRef.current;
    runRef.current = null;
    if (inflight?.traceId)
      void cancelPreviewStream(inflight.serial, inflight.traceId);
    setSelectedDeviceId('');
    setLines([]);
    setOutcome(null);
    setRunning(false);
  }, [open]);

  const selected = linkedDevices.find(
    (row) => row.device.id === selectedDeviceId
  );
  const deviceState = selected ? deviceFsmStateOf(selected.device) : null;
  const deviceReady = deviceState
    ? isDeviceFsmDispatchable(deviceState)
    : false;

  const handleRun = useCallback(async () => {
    if (!selected || !loginTemplate) return;
    const controller = new AbortController();
    abortRef.current = controller;
    runRef.current = { serial: selected.device.serial, traceId: null };
    setRunning(true);
    setLines([]);
    setOutcome(null);
    try {
      await previewScenarioStream(
        selected.device.serial,
        loginTemplate.steps ?? [],
        (event) => {
          if (event.event === 'start') {
            if (runRef.current) {
              runRef.current.traceId = String(event.trace_id ?? '') || null;
            }
          } else if (event.event === 'step_done') {
            setLines((prev) => [
              ...prev,
              {
                index: Number(event.index ?? prev.length) + 1,
                type: String(event.type ?? ''),
                ok: event.ok !== false,
                message: String(event.message ?? '')
              }
            ]);
          } else if (event.event === 'done') {
            setOutcome({
              ok: event.success === true,
              message: String(event.failed_message ?? '')
            });
          } else if (event.event === 'error') {
            setOutcome({ ok: false, message: String(event.error ?? '') });
          }
        },
        controller.signal,
        // The backend resolves this account's password and TOTP from the id,
        // and refuses when the account is not linked to this phone.
        { __ACCOUNT_ID__: account.id }
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        setOutcome({ ok: false, message: (err as Error).message });
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (runRef.current?.serial === selected.device.serial)
        runRef.current = null;
      setRunning(false);
      // The scenario writes the platform session itself; refresh what reads it.
      void qc.invalidateQueries({
        queryKey: ['devices', selected.device.id, 'platform-sessions']
      });
    }
  }, [selected, loginTemplate, account.id, qc]);

  useEffect(() => {
    if (!outcome) return;
    if (outcome.ok) toast.success(t('runSuccess'));
    else toast.error(outcome.message || t('runFailed'));
  }, [outcome, t]);

  const gateHint =
    outcome && !outcome.ok
      ? lines.some(
          (line) =>
            !line.ok &&
            GATE_HINT_REASONS.some((reason) => line.message.includes(reason))
        )
        ? t('hintAlreadySignedIn')
        : null
      : null;

  // "not found" is only true once the queries have answered — reporting it
  // while they are still in flight tells the operator the wrong thing.
  const loading = loadingLinks || loadingTemplates;
  const blockedReason = loading
    ? t('loading')
    : !loginTemplate
      ? t('noTemplate', { platform: account.platform })
      : linkedDevices.length === 0
        ? t('noDevice')
        : !selected
          ? t('pickDevice')
          : !deviceReady
            ? t('deviceOffline', { state: deviceState ?? '' })
            : null;

  if (!canUpdate) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline' className='h-8 gap-1.5 text-xs'>
          <LogIn size={14} />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>
            {account.display_name || account.username} · {account.platform}
          </p>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          <div>
            <p className='mb-2 text-xs font-medium'>{t('deviceSection')}</p>
            {loading ? (
              <p className='text-sm text-muted-foreground'>{t('loading')}</p>
            ) : linkedDevices.length === 0 ? (
              <p className='text-sm text-muted-foreground'>{t('noDevice')}</p>
            ) : (
              <ul className='max-h-40 space-y-1 overflow-y-auto rounded-lg border border-border/60 p-2'>
                {linkedDevices.map(({ link, device }) => {
                  const state = deviceFsmStateOf(device);
                  return (
                    <li key={link.id}>
                      <button
                        type='button'
                        disabled={running}
                        onClick={() => setSelectedDeviceId(device.id)}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted/50',
                          selectedDeviceId === device.id && 'bg-muted'
                        )}
                      >
                        <Smartphone
                          size={14}
                          className='shrink-0 text-muted-foreground'
                        />
                        <span className='min-w-0 flex-1'>
                          <span className='block truncate text-sm font-medium'>
                            {deviceLabel(device)}
                            {link.is_primary ? ` · ${t('primary')}` : ''}
                          </span>
                          <span className='block truncate text-[10px] text-muted-foreground'>
                            {device.serial} · {state}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {lines.length > 0 || outcome ? (
            <div className='space-y-1 rounded-lg border bg-muted/20 p-3'>
              <p className='text-xs font-medium'>{t('progress')}</p>
              <ul className='max-h-48 space-y-0.5 overflow-y-auto'>
                {lines.map((line) => (
                  <li
                    key={`${line.index}-${line.type}`}
                    className='flex items-start gap-1.5 text-[11px]'
                  >
                    {line.ok ? (
                      <CheckCircle2
                        size={12}
                        className='mt-0.5 shrink-0 text-emerald-600'
                      />
                    ) : (
                      <XCircle
                        size={12}
                        className='mt-0.5 shrink-0 text-destructive'
                      />
                    )}
                    <span className='min-w-0 flex-1'>
                      <span className='font-mono'>{line.type}</span>
                      {line.message ? (
                        <span className='text-muted-foreground'>
                          {' '}
                          — {line.message}
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
              {outcome ? (
                <p
                  className={cn(
                    'pt-1 text-xs font-medium',
                    outcome.ok ? 'text-emerald-600' : 'text-destructive'
                  )}
                >
                  {outcome.ok
                    ? t('runSuccess')
                    : outcome.message || t('runFailed')}
                </p>
              ) : null}
              {gateHint ? (
                <p className='text-[11px] text-muted-foreground'>{gateHint}</p>
              ) : null}
            </div>
          ) : null}

          {blockedReason && !running ? (
            <p className='text-xs text-muted-foreground'>{blockedReason}</p>
          ) : null}

          <Button
            className='w-full'
            disabled={running || Boolean(blockedReason)}
            onClick={handleRun}
          >
            {running ? (
              <>
                <Loader2 size={14} className='mr-2 animate-spin' />
                {t('running')}
              </>
            ) : (
              t('submit')
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
