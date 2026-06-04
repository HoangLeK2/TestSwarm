'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { CheckCircle2, Copy, Loader2, Send, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import Image from 'next/image';
import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { getDeviceAgentWsBase, getDeviceAgentWsUrl } from '@/lib/farm-api';
import { ROUTES } from '@/config/routes';
import { invalidateDeviceFleetQueries } from '../../hooks/use-devices';
import {
  getRelayConnectionState,
  isRelayOperational
} from '../../lib/relay-agent-status';
import {
  devicesApi,
  isPendingDevice,
  PENDING_SERIAL_PREFIX,
  relayAgentsApi,
  type DeviceOut,
  type RelayAgentOut
} from '../../services/manage-api';

/** Serial for ADB on relay: real serial, or adb_serial when DB row is still pending-*. */
function resolveRelayPushTarget(
  device: DeviceOut,
  relayMap?: Record<string, RelayAgentOut>
): { relayId: string; serial: string } | null {
  const serial = isPendingDevice(device)
    ? (device.adb_serial ?? '').trim()
    : (device.serial ?? '').trim();
  if (!serial) return null;

  let relayId = (device.relay_id ?? '').trim();
  if (!relayId && relayMap) {
    const agent =
      (device.adb_serial ? relayMap[device.adb_serial] : undefined) ??
      (device.adb_ip ? relayMap[device.adb_ip] : undefined);
    relayId = (agent?.relay_id ?? '').trim();
  }
  if (!relayId) return null;
  return { relayId, serial };
}

/** ADB targets on online relays; skip placeholders and serials already bound to a real device row. */
function relayPushCandidates(
  relayAgents: RelayAgentOut[] | undefined,
  registeredSerials: Set<string> | undefined
): { relayId: string; serial: string }[] {
  if (!relayAgents?.length) return [];
  const taken = registeredSerials ?? new Set<string>();
  const out: { relayId: string; serial: string }[] = [];
  for (const agent of relayAgents) {
    if (agent.live_connected === false) continue;
    if (!isRelayOperational(getRelayConnectionState(agent))) continue;
    for (const s of agent.serials) {
      if (!s || s.startsWith(PENDING_SERIAL_PREFIX)) continue;
      if (taken.has(s)) continue;
      out.push({ relayId: agent.relay_id, serial: s });
    }
  }
  return out;
}

const POLL_INTERVAL_MS = 2000;

export function ConnectDialog({
  device,
  open,
  onClose,
  relayMap,
  relayAgents,
  registeredSerials
}: {
  device: DeviceOut;
  open: boolean;
  onClose: () => void;
  relayMap?: Record<string, RelayAgentOut>;
  relayAgents?: RelayAgentOut[];
  /** Primary serials (and adb_serial) already used by non-pending devices — excluded from relay pick list. */
  registeredSerials?: Set<string>;
}) {
  const t = useTranslations('devicesList.connectDialog');
  const qc = useQueryClient();
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [pushingUrl, setPushingUrl] = useState(false);
  const [connectedDevice, setConnectedDevice] = useState<DeviceOut | null>(
    null
  );
  const [relayPickIdx, setRelayPickIdx] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const openedAtRef = useRef<number>(0);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => {
    if (!open) return;
    setRelayPickIdx(0);
  }, [open, device?.id]);

  // Reset state when dialog closes or device changes
  useEffect(() => {
    if (!open) {
      stopPolling();
      setConnectedDevice(null);
      setQrDataUrl('');
      setPushingUrl(false);
      openedAtRef.current = 0;
      return;
    }
    openedAtRef.current = Date.now();
    if (!device?.device_key) {
      setQrDataUrl('');
      return;
    }
    const wsUrl = getDeviceAgentWsUrl(`key=${device.device_key}`);
    QRCode.toDataURL(wsUrl, { width: 220, margin: 2 })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(''));
  }, [open, device?.device_key]);

  // Poll device list for pairing completion
  useEffect(() => {
    if (!open || !device?.id || connectedDevice) return;
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const list = await devicesApi.list();
        const found = list.find((d) => d.id === device.id);
        if (found && !isPendingDevice(found)) {
          const sessions = await devicesApi.sessions(found.id);
          const hasFreshActiveSession = sessions.some((session) => {
            if (session.disconnected_at) return false;
            const connectedAtTs = Date.parse(session.connected_at);
            return (
              Number.isFinite(connectedAtTs) &&
              connectedAtTs >= openedAtRef.current
            );
          });
          if (!hasFreshActiveSession) return;
          stopPolling();
          setConnectedDevice(found);
          toast.success(t('successToast'));
          invalidateDeviceFleetQueries(qc);
        }
      } catch {
        // ignore transient errors — try again next tick
      }
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [open, device?.id, connectedDevice, qc, t]);

  const candidates = useMemo(
    () => relayPushCandidates(relayAgents, registeredSerials),
    [relayAgents, registeredSerials]
  );

  const directPush = useMemo(
    () => (device ? resolveRelayPushTarget(device, relayMap) : null),
    [device, relayMap]
  );

  const relayPush = useMemo(() => {
    if (!device) return null;
    if (directPush) return directPush;
    if (isPendingDevice(device) && candidates.length > 0) {
      const i = Math.min(Math.max(0, relayPickIdx), candidates.length - 1);
      return candidates[i]!;
    }
    return null;
  }, [device, directPush, candidates, relayPickIdx]);

  const showRelayPicker = Boolean(
    device && isPendingDevice(device) && !directPush && candidates.length > 1
  );

  async function pushConnectUrl() {
    if (!relayPush || !device) return;
    setPushingUrl(true);
    try {
      const res = await relayAgentsApi.pushConnectUrl(
        relayPush.relayId,
        relayPush.serial,
        {
          deviceId: isPendingDevice(device) ? device.id : undefined,
          wsBaseUrl: getDeviceAgentWsBase()
        }
      );
      if (!res.ok) {
        toast.error(res.error || t('errorPushToPhone'));
        return;
      }
      toast.success(t('sentToPhone'));
    } catch {
      toast.error(t('errorPushToPhone'));
    } finally {
      setPushingUrl(false);
    }
  }

  const wsUrl = device?.device_key
    ? getDeviceAgentWsUrl(`key=${device.device_key}`)
    : '';

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent className='max-w-sm' zIndex={20000}>
        <DialogHeader>
          <DialogTitle>
            {connectedDevice ? t('successTitle') : t('title')}
          </DialogTitle>
        </DialogHeader>

        {connectedDevice ? (
          <div className='flex flex-col gap-4 pt-2'>
            <div className='flex flex-col items-center gap-3 rounded-lg bg-green-500/10 py-5'>
              <div className='relative'>
                <div className='absolute inset-0 rounded-full bg-green-500/20 blur-md' />
                <div className='relative flex size-14 items-center justify-center rounded-full bg-green-500/15 ring-1 ring-green-500/30'>
                  <CheckCircle2 size={28} className='text-green-500' />
                </div>
              </div>
              <div className='text-center'>
                <p className='font-semibold text-foreground'>
                  {connectedDevice.brand || ''}{' '}
                  {connectedDevice.model ||
                    connectedDevice.name ||
                    connectedDevice.serial}
                </p>
                <p className='text-xs text-muted-foreground'>
                  {t('successMessage')}
                </p>
              </div>
            </div>

            <div className='rounded-lg border bg-muted/30'>
              <div className='flex items-center gap-3 px-3 py-2.5'>
                <Smartphone
                  size={14}
                  className='shrink-0 text-muted-foreground'
                />
                <span className='min-w-0 flex-1 text-xs text-muted-foreground'>
                  {t('infoSerial')}
                </span>
                <span className='font-mono text-xs font-medium text-foreground'>
                  {connectedDevice.serial}
                </span>
              </div>
              {connectedDevice.android_version && (
                <>
                  <Separator />
                  <div className='flex items-center gap-3 px-3 py-2.5'>
                    <span className='min-w-0 flex-1 text-xs text-muted-foreground'>
                      {t('infoAndroid')}
                    </span>
                    <span className='text-xs font-medium text-foreground'>
                      {connectedDevice.android_version}
                    </span>
                  </div>
                </>
              )}
            </div>

            <Button asChild className='w-full'>
              <Link
                href={ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(
                  connectedDevice.serial
                )}
              >
                {t('controlNow')}
              </Link>
            </Button>
            <Button variant='outline' className='w-full' onClick={onClose}>
              {t('close')}
            </Button>
          </div>
        ) : (
          <div className='flex flex-col gap-3 pt-2'>
            <p className='text-sm text-muted-foreground'>
              {t.rich('description', {
                strong: (chunks) => <strong>{chunks}</strong>
              })}
            </p>
            <div className='flex gap-2'>
              <input
                readOnly
                value={wsUrl}
                className='flex-1 rounded-md border bg-muted px-2 py-1.5 font-mono text-xs'
              />
              <Button
                size='sm'
                variant='outline'
                onClick={() => {
                  navigator.clipboard.writeText(wsUrl);
                  toast.success(t('copied'));
                }}
              >
                <Copy size={14} />
              </Button>
            </div>
            {showRelayPicker ? (
              <div className='flex flex-col gap-1.5'>
                <label
                  className='text-xs font-medium text-foreground'
                  htmlFor='relay-serial-pick'
                >
                  {t('pickAdbSerial')}
                </label>
                <select
                  id='relay-serial-pick'
                  className='h-9 w-full rounded-md border border-input bg-background px-2 font-mono text-xs'
                  value={relayPickIdx}
                  onChange={(e) => setRelayPickIdx(Number(e.target.value))}
                >
                  {candidates.map((c, idx) => (
                    <option key={`${c.relayId}:${c.serial}`} value={idx}>
                      {c.serial}
                    </option>
                  ))}
                </select>
                <p className='text-[11px] text-muted-foreground'>
                  {t('pickAdbSerialHint')}
                </p>
              </div>
            ) : null}
            {relayPush ? (
              <Button
                type='button'
                variant='outline'
                className='w-full gap-2'
                disabled={pushingUrl}
                onClick={pushConnectUrl}
              >
                {pushingUrl ? (
                  <Loader2 size={14} className='animate-spin' />
                ) : (
                  <Send size={14} />
                )}
                {pushingUrl ? t('sendingToPhone') : t('sendToPhone')}
              </Button>
            ) : null}
            {qrDataUrl ? (
              <Image
                src={qrDataUrl}
                alt={t('qrAlt')}
                width={200}
                height={200}
                unoptimized
                className='mx-auto rounded-lg border bg-white'
              />
            ) : (
              <div className='mx-auto flex size-[200px] items-center justify-center rounded-lg border bg-muted text-sm text-muted-foreground'>
                {t('generatingQr')}
              </div>
            )}
            <div
              className='mt-1 flex items-center justify-center gap-2 text-xs text-muted-foreground'
              role='status'
              aria-live='polite'
            >
              <Loader2 size={12} className='animate-spin' />
              {t('waiting')}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
