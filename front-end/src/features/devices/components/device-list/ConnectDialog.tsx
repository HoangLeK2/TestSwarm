'use client';

import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getDeviceAgentWsUrl } from '@/lib/farm-api';
import type { DeviceOut } from '../../services/manage-api';

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
  const [qrDataUrl, setQrDataUrl] = useState<string>('');

  useEffect(() => {
    if (!open || !device?.device_key) {
      setQrDataUrl('');
      return;
    }
    const wsUrl = getDeviceAgentWsUrl(`key=${device.device_key}`);
    QRCode.toDataURL(wsUrl, { width: 220, margin: 2 })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(''));
  }, [open, device?.device_key]);

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
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <div className='flex flex-col gap-3 pt-2'>
          <p className='text-sm text-muted-foreground'>
            {t.rich('description', { strong: (chunks) => <strong>{chunks}</strong> })}
          </p>
          <div className='flex gap-2'>
            <input readOnly value={wsUrl} className='flex-1 rounded-md border bg-muted px-2 py-1.5 font-mono text-xs' />
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
        </div>
      </DialogContent>
    </Dialog>
  );
}

