'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import QRCode from 'qrcode';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
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
import { Plus, Copy, Check, CheckCircle2, Loader2, QrCode, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { devicesApi, isPendingDevice } from '@/features/devices/services/manage-api';
import { getDeviceAgentWsUrl } from '@/lib/farm-api';
import { useTranslations } from 'next-intl';
import type { DeviceOut } from '@/features/devices/services/manage-api';

type Step = 'form' | 'confirm' | 'qr' | 'connected';

const POLL_INTERVAL_MS = 2000;

export function RegisterDeviceDialog() {
  const t = useTranslations('devicesRegister');
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>('form');
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [registeredDevice, setRegisteredDevice] = useState<DeviceOut | null>(null);
  const [connectedDevice, setConnectedDevice] = useState<DeviceOut | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const qc = useQueryClient();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
      setRegisteredDevice(null);
      setConnectedDevice(null);
      setQrDataUrl(null);
      setCopied(false);
    }
  }, [open, stopPolling]);

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
        if (found && !isPendingDevice(found)) {
          stopPolling();
          setConnectedDevice(found);
          setStep('connected');
          qc.invalidateQueries({ queryKey: ['devices'] });
        }
      } catch {
        // ignore transient errors
      }
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [step, registeredDevice, qc, stopPolling]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const device = await devicesApi.register({
        name: name.trim() || undefined,
        description: description.trim() || undefined
      });
      setRegisteredDevice(device);
      setStep('confirm');
      qc.invalidateQueries({ queryKey: ['devices'] });
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

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          {t('title')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-sm' onInteractOutside={() => {}}>
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
            <Button type='submit' className='w-full' disabled={loading}>
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
