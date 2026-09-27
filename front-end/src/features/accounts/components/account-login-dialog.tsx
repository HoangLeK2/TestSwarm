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
import { ROUTES } from '@/config/routes';
import { useDevices } from '@/features/devices/hooks/use-devices';
import type { DeviceOut } from '@/features/devices/services/manage-api';
import {
  cancelPreviewStream,
  previewScenarioStream
} from '@/features/devices/services/api';
import { orgScenariosApi } from '@/features/org-scenarios/services/api';
import type { OrgScenarioOut } from '@/features/org-scenarios/services/api';
import {
  deviceFsmStateOf,
  isDeviceFsmDispatchable
} from '@/features/devices/lib/device-fsm';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
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
import { Link } from '@/i18n/navigation';
import { cn } from '@/lib/utils';

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
  const [loginScenario, setLoginScenario] = useState<OrgScenarioOut | null>(
    null
  );
  const [loginScenarioError, setLoginScenarioError] = useState(false);
  const [loadingLoginScenario, setLoadingLoginScenario] = useState(false);
  const ensuredPlatformRef = useRef<string | null>(null);
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
  const loginSteps = useMemo(
    () =>
      Array.isArray(loginScenario?.body_json?.steps)
        ? loginScenario.body_json.steps
        : [],
    [loginScenario]
  );

  const ensureLoginScenario = useCallback(async () => {
    if (loginScenario) return loginScenario;
    setLoadingLoginScenario(true);
    setLoginScenarioError(false);
    try {
      const ensured = await orgScenariosApi.ensureAccountLogin({
        platform: account.platform
      });
      setLoginScenario(ensured);
      void qc.invalidateQueries({ queryKey: ['org-scenarios'] });
      return ensured;
    } catch (error) {
      ensuredPlatformRef.current = null;
      setLoginScenarioError(true);
      throw error;
    } finally {
      setLoadingLoginScenario(false);
    }
  }, [account.platform, loginScenario, qc]);

  useEffect(() => {
    if (!open || loginScenario || loginScenarioError) return;
    if (ensuredPlatformRef.current === account.platform) return;
    ensuredPlatformRef.current = account.platform;
    void ensureLoginScenario().catch(() => undefined);
  }, [
    account.platform,
    ensureLoginScenario,
    loginScenario,
    loginScenarioError,
    open
  ]);

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
    if (!selected || !loginScenario || loginSteps.length === 0) return;
    const controller = new AbortController();
    abortRef.current = controller;
    runRef.current = { serial: selected.device.serial, traceId: null };
    setRunning(true);
    setLines([]);
    setOutcome(null);
    try {
      const ensuredScenario = await ensureLoginScenario();
      const ensuredSteps = Array.isArray(ensuredScenario.body_json?.steps)
        ? ensuredScenario.body_json.steps
        : [];
      if (ensuredSteps.length === 0) {
        throw new Error(t('noTemplate', { platform: account.platform }));
      }
      await previewScenarioStream(
        selected.device.serial,
        ensuredSteps,
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
        { __ACCOUNT_ID__: account.id },
        null,
        ensuredScenario.id,
        null,
        true
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
  }, [
    selected,
    loginScenario,
    loginSteps.length,
    ensureLoginScenario,
    t,
    account.platform,
    account.id,
    qc
  ]);

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
  const loading =
    loadingLinks ||
    loadingLoginScenario ||
    (!loginScenario && !loginScenarioError);
  const blockedReason = loading
    ? t('loading')
    : !loginScenario || loginSteps.length === 0
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
      {/* DialogContent's own `sm:max-w-lg` outranks a bare `max-w-*` here —
          tailwind-merge only replaces a class at the same variant — so the
          override has to carry the `sm:` prefix or the mirror stays boxed into
          32rem next to a truncated device card. */}
      <DialogContent className='z-[1000] w-[min(96vw,72rem)] sm:max-w-none'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>
            {account.display_name || account.username} · {account.platform}
          </p>
        </DialogHeader>
        <div className='grid gap-6 pt-2 sm:grid-cols-[minmax(0,340px)_minmax(0,1fr)]'>
          {/* The step list says what the scenario decided; the mirror says what
              the phone actually shows. A login is exactly where those two
              diverge — a popup or a checkpoint reads as a green step. Keyed by
              serial so switching phones restarts the stream on the new one. */}
          <div className='min-w-0'>
            {selected ? (
              <DeviceControlEmbed
                key={selected.device.serial}
                initialSerial={selected.device.serial}
                compact
                hideStepMonitor
                readOnlyPreview
                forceStream
              />
            ) : (
              <div className='flex h-full min-h-[280px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-3 text-center'>
                <p className='text-[11px] text-muted-foreground'>
                  {t('pickDevice')}
                </p>
              </div>
            )}
          </div>
          <div className='min-w-0 space-y-4'>
            <div className='flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 p-3'>
              <div className='min-w-0'>
                <p className='text-xs text-muted-foreground'>
                  {t('scenarioSection')}
                </p>
                <p className='mt-0.5 truncate text-sm font-medium'>
                  {loginScenario?.name ?? t('preparingScenario')}
                </p>
                {loginScenario ? (
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {t('scenarioDescription', {
                      platform: account.platform
                    })}
                  </p>
                ) : null}
              </div>
              {loginScenario ? (
                <Button asChild size='sm' variant='outline'>
                  <Link
                    href={ROUTES.DEVICES.CONTROL_RECORD_EDIT_ORG_SCENARIO(
                      loginScenario.id,
                      { returnTo: ROUTES.ACCOUNTS.ROOT }
                    )}
                  >
                    {t('editScenario')}
                  </Link>
                </Button>
              ) : null}
            </div>

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
                  <p className='text-[11px] text-muted-foreground'>
                    {gateHint}
                  </p>
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
        </div>
      </DialogContent>
    </Dialog>
  );
}
