'use client';

import { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { CheckCircle2, Copy, Loader2, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import Image from 'next/image';
import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { getDeviceAgentWsUrl } from '@/lib/farm-api';
import { ROUTES } from '@/config/routes';
import { devicesApi, isPendingDevice, type DeviceOut } from '../../services/manage-api';

const POLL_INTERVAL_MS = 2000;

export function ConnectDialog({
  device,
  open,
  onClose
}: {
  device: DeviceOut;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations('devicesList.connectDialog');
  const qc = useQueryClient();
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [connectedDevice, setConnectedDevice] = useState<DeviceOut | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  // Reset state when dialog closes or device changes
  useEffect(() => {
    if (!open) {
      stopPolling();
      setConnectedDevice(null);
      setQrDataUrl('');
      return;
    }
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
          stopPolling();
          setConnectedDevice(found);
          toast.success(t('successToast'));
          qc.invalidateQueries({ queryKey: ['devices'] });
        }
      } catch {
        // ignore transient errors — try again next tick
      }
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [open, device?.id, connectedDevice, qc, t]);

  const wsUrl = device?.device_key ? getDeviceAgentWsUrl(`key=${device.device_key}`) : '';

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent className='z-[1000] max-w-sm'>
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
                  {connectedDevice.brand || ''} {connectedDevice.model || connectedDevice.name || connectedDevice.serial}
                </p>
                <p className='text-xs text-muted-foreground'>{t('successMessage')}</p>
              </div>
            </div>

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
            </div>

            <Button asChild className='w-full'>
              <Link href={ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(connectedDevice.serial)}>
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
              {t.rich('description', { strong: (chunks) => <strong>{chunks}</strong> })}
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
