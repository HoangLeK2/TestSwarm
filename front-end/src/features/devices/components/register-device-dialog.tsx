'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import QRCode from 'qrcode';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import { Separator } from '@/components/ui/separator';
import { Plus, Copy, Check, CheckCircle2, Loader2, QrCode, Send, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { devicesApi, relayAgentsApi, isPendingDevice } from '@/features/devices/services/manage-api';
import { getDeviceAgentWsUrl } from '@/lib/farm-api';
import { useTranslations } from 'next-intl';
import type { DeviceOut, RelayAgentOut } from '@/features/devices/services/manage-api';

type Step = 'form' | 'confirm' | 'qr' | 'connected';

const POLL_INTERVAL_MS = 2000;

type RelayDeviceChoice = {
  id: string;
  relayId: string;
  relayLabel: string;
  serial: string;
};

export function RegisterDeviceDialog({
  relayAgents = [],
  registeredSerials = new Set<string>(),
}: {
  relayAgents?: RelayAgentOut[];
  registeredSerials?: Set<string>;
}) {
  const t = useTranslations('devicesRegister');
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>('form');
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedRelayDeviceId, setSelectedRelayDeviceId] = useState('');
  const [registeredDevice, setRegisteredDevice] = useState<DeviceOut | null>(null);
  const [connectedDevice, setConnectedDevice] = useState<DeviceOut | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pushingUrl, setPushingUrl] = useState(false);
  const qc = useQueryClient();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qrOpenedAtRef = useRef<number>(0);

  const relayDeviceChoices = useMemo<RelayDeviceChoice[]>(() => {
    const choices: RelayDeviceChoice[] = [];
    for (const agent of relayAgents) {
      if (agent.status !== 'online') continue;
      for (const serial of agent.serials) {
        if (!serial || serial.startsWith('pending-') || registeredSerials.has(serial)) continue;
        choices.push({
          id: `${agent.relay_id}::${serial}`,
          relayId: agent.relay_id,
          relayLabel: agent.hostname || agent.relay_id,
          serial,
        });
      }
    }
    return choices;
  }, [relayAgents, registeredSerials]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!open) {
      stopPolling();
      setStep('form');
      setName('');
      setDescription('');
      setSelectedRelayDeviceId('');
      setRegisteredDevice(null);
      setConnectedDevice(null);
      setQrDataUrl(null);
      setCopied(false);
      setPushingUrl(false);
      qrOpenedAtRef.current = 0;
    }
  }, [open, stopPolling]);

  useEffect(() => {
    if (
      relayDeviceChoices.length > 0 &&
      (!selectedRelayDeviceId || !relayDeviceChoices.some((choice) => choice.id === selectedRelayDeviceId))
    ) {
      setSelectedRelayDeviceId(relayDeviceChoices[0].id);
    }
  }, [relayDeviceChoices, selectedRelayDeviceId]);

  useEffect(() => {
    if (step !== 'qr' || !registeredDevice?.device_key) {
      setQrDataUrl(null);
      return;
    }
    const wsUrl = getDeviceAgentWsUrl(`key=${registeredDevice.device_key}`);
    QRCode.toDataURL(wsUrl, { width: 240, margin: 2 })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(null));
  }, [step, registeredDevice?.device_key]);

  useEffect(() => {
    if (step !== 'qr' || !registeredDevice) return;
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const list = await devicesApi.list();
        const found = list.find((d) => d.id === registeredDevice.id);
        if (!found || isPendingDevice(found)) return;
        const sessions = await devicesApi.sessions(found.id);
        const hasFreshActiveSession = sessions.some((session) => {
          if (session.disconnected_at) return false;
          const connectedAtTs = Date.parse(session.connected_at);
          return Number.isFinite(connectedAtTs) && connectedAtTs >= qrOpenedAtRef.current;
        });
        if (!hasFreshActiveSession) return;
        stopPolling();
        setConnectedDevice(found);
        setStep('connected');
        qc.invalidateQueries({ queryKey: ['devices'] });
      } catch {
        // ignore transient errors
      }
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [step, registeredDevice, qc, stopPolling]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const choice = relayDeviceChoices.find((item) => item.id === selectedRelayDeviceId);
    if (!choice) {
      toast.error(t('errorNoDevice'));
      return;
    }
    setLoading(true);
    try {
      const displayName = [name.trim(), description.trim()].filter(Boolean).join(' — ');
      const device = await relayAgentsApi.registerDevice(choice.relayId, choice.serial, {
        name: displayName || choice.serial,
      });
      setRegisteredDevice(device);
      qrOpenedAtRef.current = Date.now();
      setStep('qr');
      qc.invalidateQueries({ queryKey: ['devices'] });
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
    } catch {
      toast.error(t('errorRegister'));
    } finally {
      setLoading(false);
    }
  }

  function copyLink() {
    if (!registeredDevice) return;
    const wsUrl = getDeviceAgentWsUrl(`key=${registeredDevice.device_key}`);
    navigator.clipboard.writeText(wsUrl).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => toast.error(t('errorCopy'))
    );
  }

  async function pushConnectUrl() {
    if (!registeredDevice?.relay_id) return;
    setPushingUrl(true);
    try {
      const res = await relayAgentsApi.pushConnectUrl(registeredDevice.relay_id, registeredDevice.serial);
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

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          {t('title')}
        </Button>
      </DialogTrigger>
      <DialogContent className='max-w-sm' zIndex={20000} onInteractOutside={() => {}}>
        <DialogHeader>
          <DialogTitle>
            {step === 'form' && t('title')}
            {step === 'confirm' && t('titleConfirm')}
            {step === 'qr' && t('titleQr')}
            {step === 'connected' && t('titleConnected')}
          </DialogTitle>
        </DialogHeader>

        {/* ── Step 1: form ── */}
        {step === 'form' && (
          <form onSubmit={handleSubmit} className='flex flex-col gap-4 pt-2'>
            <p className='text-sm text-muted-foreground'>
              {t.rich('description', { strong: (c) => <strong>{c}</strong> })}
            </p>
            <div className='space-y-2'>
              <Label htmlFor='reg-name'>{t('nameLabel')}</Label>
              <Input
                id='reg-name'
                placeholder={t('namePlaceholder')}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className='space-y-2'>
              <Label htmlFor='reg-relay-device'>{t('deviceLabel')}</Label>
              <Select
                value={selectedRelayDeviceId}
                onValueChange={setSelectedRelayDeviceId}
                disabled={relayDeviceChoices.length === 0}
              >
                <SelectTrigger id='reg-relay-device' className='w-full'>
                  <SelectValue placeholder={t('devicePlaceholder')} />
                </SelectTrigger>
                <SelectContent className='z-[20002]'>
                  {relayDeviceChoices.map((choice) => (
                    <SelectItem key={choice.id} value={choice.id}>
                      <span className='font-mono'>{choice.serial}</span>
                      <span className='text-xs text-muted-foreground'> · {choice.relayLabel}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {relayDeviceChoices.length === 0 && (
                <p className='text-xs text-muted-foreground'>{t('noAvailableDevices')}</p>
              )}
            </div>
            <div className='space-y-2'>
              <Label htmlFor='reg-desc'>{t('descLabel')}</Label>
              <Textarea
                id='reg-desc'
                placeholder={t('descPlaceholder')}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className='resize-none'
              />
            </div>
            <Button type='submit' className='w-full' disabled={loading || relayDeviceChoices.length === 0}>
              {loading ? t('submitting') : t('submit')}
            </Button>
          </form>
        )}

        {/* ── Step 2: confirm connect ── */}
        {step === 'confirm' && registeredDevice && (
          <div className='flex flex-col gap-4 pt-2'>
            <p className='text-sm text-muted-foreground'>
              {t.rich('confirmMessage', {
                strong: (c) => <strong className='text-foreground'>{c}</strong>,
                name: registeredDevice.name || registeredDevice.serial,
              })}
            </p>
            <Button className='w-full gap-2' onClick={() => setStep('qr')}>
              <QrCode size={15} />
              {t('connectNow')}
            </Button>
            <Button variant='outline' className='w-full' onClick={() => setOpen(false)}>
              {t('connectLater')}
            </Button>
          </div>
        )}

        {/* ── Step 3: QR + waiting ── */}
        {step === 'qr' && registeredDevice && (
          <div className='flex flex-col items-center gap-4 pt-2'>
            <p className='text-center text-sm text-muted-foreground'>
              {t.rich('qrInstruction', { strong: (c) => <strong>{c}</strong> })}
            </p>

            {qrDataUrl ? (
              <img
                src={qrDataUrl}
                alt='QR'
                className='rounded-lg border bg-white p-2'
                width={200}
                height={200}
              />
            ) : (
              <div className='flex h-[200px] w-[200px] items-center justify-center rounded-lg border bg-muted text-sm text-muted-foreground'>
                {t('generatingQr')}
              </div>
            )}

            <div className='flex w-full gap-2'>
              <input
                readOnly
                value={getDeviceAgentWsUrl(`key=${registeredDevice.device_key}`)}
                className='flex-1 rounded-md border bg-muted px-2 py-1.5 font-mono text-xs'
              />
              <Button size='sm' variant='outline' onClick={copyLink}>
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </Button>
            </div>

            {registeredDevice.relay_id && (
              <Button
                type='button'
                variant='outline'
                className='w-full gap-2'
                disabled={pushingUrl}
                onClick={pushConnectUrl}
              >
                {pushingUrl ? <Loader2 size={14} className='animate-spin' /> : <Send size={14} />}
                {pushingUrl ? t('sendingToPhone') : t('sendToPhone')}
              </Button>
            )}

            <div className='flex items-center gap-2 text-sm text-muted-foreground'>
              <Loader2 size={14} className='animate-spin' />
              {t('waiting')}
            </div>

            <Button variant='ghost' size='sm' className='w-full text-xs' onClick={() => setOpen(false)}>
              {t('close')}
            </Button>
          </div>
        )}

        {/* ── Step 4: connected ── */}
        {step === 'connected' && connectedDevice && (
          <div className='flex flex-col gap-4 pt-2'>
            {/* Success banner */}
            <div className='flex flex-col items-center gap-3 rounded-lg bg-green-500/10 py-5'>
              <div className='relative'>
                <div className='absolute inset-0 rounded-full bg-green-500/20 blur-md' />
                <div className='relative flex size-14 items-center justify-center rounded-full bg-green-500/15 ring-1 ring-green-500/30'>
                  <CheckCircle2 size={28} className='text-green-500' />
                </div>
              </div>
              <div className='text-center'>
                <p className='font-semibold text-foreground'>
                  {connectedDevice.brand} {connectedDevice.model}
                </p>
                <p className='text-xs text-muted-foreground'>{t('successMessage')}</p>
              </div>
            </div>

            {/* Device info */}
            <div className='rounded-lg border bg-muted/30'>
              <div className='flex items-center gap-3 px-3 py-2.5'>
                <Smartphone size={14} className='shrink-0 text-muted-foreground' />
                <span className='min-w-0 flex-1 text-xs text-muted-foreground'>{t('infoSerial')}</span>
                <span className='font-mono text-xs font-medium text-foreground'>{connectedDevice.serial}</span>
              </div>
              {connectedDevice.android_version && (
                <>
                  <Separator />
                  <div className='flex items-center gap-3 px-3 py-2.5'>
                    <span className='min-w-0 flex-1 text-xs text-muted-foreground'>{t('infoAndroid')}</span>
                    <span className='text-xs font-medium text-foreground'>{connectedDevice.android_version}</span>
                  </div>
                </>
              )}
              {connectedDevice.screen_width > 0 && connectedDevice.screen_height > 0 && (
                <>
                  <Separator />
                  <div className='flex items-center gap-3 px-3 py-2.5'>
                    <span className='min-w-0 flex-1 text-xs text-muted-foreground'>{t('infoResolution')}</span>
                    <span className='text-xs font-medium text-foreground'>
                      {connectedDevice.screen_width} × {connectedDevice.screen_height}
                    </span>
                  </div>
                </>
              )}
            </div>

            <Button asChild className='w-full'>
              <Link href={ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(connectedDevice.serial)}>
                {t('controlNow')}
              </Link>
            </Button>
            <Button variant='outline' className='w-full' onClick={() => setOpen(false)}>
              {t('close')}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
