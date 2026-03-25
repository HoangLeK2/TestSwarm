'use client';

import { useState, useEffect } from 'react';
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
import { Plus } from 'lucide-react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { devicesApi } from '@/features/devices/services/manage-api';
import { getDeviceAgentWsUrl } from '@/lib/farm-api';
import type { DeviceOut } from '@/features/devices/services/manage-api';

type Step = 'form' | 'qr';

export function RegisterDeviceDialog() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>('form');
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [registeredDevice, setRegisteredDevice] = useState<DeviceOut | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!open) {
      setStep('form');
      setName('');
      setDescription('');
      setRegisteredDevice(null);
      setQrDataUrl(null);
    }
  }, [open]);

  useEffect(() => {
    if (step !== 'qr' || !registeredDevice?.device_key) {
      setQrDataUrl(null);
      return;
    }
    const wsUrl = getDeviceAgentWsUrl(`key=${registeredDevice.device_key}`);
    QRCode.toDataURL(wsUrl, { width: 260, margin: 2 })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(null));
  }, [step, registeredDevice?.device_key]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const device = await devicesApi.register({
        name: name.trim() || undefined,
        description: description.trim() || undefined
      });
      setRegisteredDevice(device);
      setStep('qr');
      qc.invalidateQueries({ queryKey: ['devices'] });
      toast.success('Đã đăng ký. Quét mã QR trên điện thoại bằng app STFService.');
    } catch {
      toast.error('Đăng ký thất bại');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          Đăng ký thiết bị
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-sm' onInteractOutside={() => {}}>
        <DialogHeader>
          <DialogTitle>
            {step === 'form' ? 'Đăng ký thiết bị' : 'Mã QR kết nối'}
          </DialogTitle>
        </DialogHeader>

        {step === 'form' && (
          <form onSubmit={handleSubmit} className='flex flex-col gap-4 pt-2'>
            <p className='text-sm text-muted-foreground'>
              Nhập thông tin thiết bị. Sau đăng ký, quét mã QR bằng app <strong>STFService</strong> trên điện thoại — thiết bị sẽ tự kết nối cloud và ghi nhận serial.
            </p>
            <div className='space-y-2'>
              <Label htmlFor='reg-name'>Tên thiết bị</Label>
              <Input
                id='reg-name'
                placeholder='VD: Điện thoại test 1'
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className='space-y-2'>
              <Label htmlFor='reg-desc'>Ghi chú (tuỳ chọn)</Label>
              <Textarea
                id='reg-desc'
                placeholder='VD: Phòng QA, máy Samsung...'
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className='resize-none'
              />
            </div>
            <Button type='submit' className='w-full' disabled={loading}>
              {loading ? 'Đang đăng ký…' : 'Đăng ký'}
            </Button>
          </form>
        )}

        {step === 'qr' && registeredDevice && (
          <div className='flex flex-col items-center gap-4 pt-2'>
            <p className='text-center text-sm text-muted-foreground'>
              Mở app <strong>STFService</strong> trên điện thoại — <strong>dán link bên dưới</strong> hoặc quét QR. App sẽ kết nối lên cloud; những lần sau app tự kết nối lại.
            </p>
            {(() => {
              const wsUrl = getDeviceAgentWsUrl(`key=${registeredDevice.device_key}`);
              return (
                <div className='w-full space-y-2'>
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
                        toast.success('Đã copy link');
                      }}
                    >
                      Copy
                    </Button>
                  </div>
                  {qrDataUrl ? (
                    <img
                      src={qrDataUrl}
                      alt='QR kết nối'
                      className='mx-auto rounded-lg border bg-white p-2'
                      width={200}
                      height={200}
                    />
                  ) : (
                    <div className='mx-auto flex h-[200px] w-[200px] items-center justify-center rounded-lg border bg-muted text-sm text-muted-foreground'>
                      Đang tạo mã QR…
                    </div>
                  )}
                </div>
              );
            })()}
            <p className='text-center text-xs text-muted-foreground'>
              Thiết bị: <span className='font-medium text-foreground'>{registeredDevice.name || 'Thiết bị mới'}</span>
            </p>
            <Button variant='outline' className='w-full' onClick={() => setOpen(false)}>
              Đóng
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
