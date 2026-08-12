'use client';

import { useState, useCallback } from 'react';
import { Smartphone, Plus, X, Star } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { useDevices } from '@/features/devices/hooks/use-devices';
import {
  useAccountDevices,
  useAssignDeviceToAccount,
  useUnassignDeviceFromAccount
} from '../hooks/use-accounts';
import type { AccountOut } from '../services/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';

function deviceLabel(d: { serial: string; name?: string | null }) {
  return d.name?.trim() || d.serial || '—';
}

export function AccountDevicesDialog({
  account,
  canUpdate
}: {
  account: AccountOut;
  canUpdate: boolean;
}) {
  const t = useTranslations('accountsFeature.devicesDialog');
  const [open, setOpen] = useState(false);

  const { data: links = [], isLoading: loadingLinks } = useAccountDevices(
    open ? account.id : ''
  );
  const { data: allDevices = [], isLoading: loadingAll } = useDevices();
  const { mutateAsync: assignDevice, isPending: assigning } =
    useAssignDeviceToAccount();
  const { mutate: unassignDevice, isPending: unassigning } =
    useUnassignDeviceFromAccount();

  const linkedDeviceIds = new Set(links.map((l) => l.device_id));
  const available = allDevices.filter((d) => !linkedDeviceIds.has(d.id));

  const handleAssign = useCallback(
    async (deviceId: string) => {
      try {
        await assignDevice({ accountId: account.id, deviceId });
      } catch {
        toast.error(t('assignError'));
      }
    },
    [account.id, assignDevice, t]
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size='icon'
          variant='ghost'
          className='size-8'
          title={t('title')}
        >
          <Smartphone size={14} />
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>
            {account.platform} — {account.username}
          </p>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          {/* Linked devices */}
          {links.length > 0 && (
            <div className='rounded-lg border border-border/60 bg-muted/20 p-3'>
              <p className='mb-2 text-xs font-medium'>
                {t('linkedDevices', { count: links.length })}
              </p>
              <ul className='max-h-32 space-y-1 overflow-y-auto'>
                {links.map((link) => {
                  const device = allDevices.find(
                    (d) => d.id === link.device_id
                  );
                  return (
                    <li
                      key={link.id}
                      className='flex items-center gap-2 rounded py-1 text-xs'
                    >
                      <Smartphone className='size-3 shrink-0' />
                      <span className='min-w-0 flex-1 truncate'>
                        {device ? deviceLabel(device) : link.device_id}
                      </span>
                      {link.is_primary && (
                        <Star size={12} className='shrink-0 text-yellow-500' />
                      )}
                      {canUpdate ? (
                        <Button
                          type='button'
                          size='sm'
                          variant='ghost'
                          className='size-6 shrink-0 text-destructive hover:bg-destructive/10'
                          disabled={unassigning}
                          onClick={() =>
                            unassignDevice(
                              {
                                accountId: account.id,
                                deviceId: link.device_id
                              },
                              {
                                onSuccess: () =>
                                  toast.success(t('removeSuccess')),
                                onError: () => toast.error(t('removeError'))
                              }
                            )
                          }
                        >
                          <X size={12} />
                        </Button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Available devices */}
          {canUpdate ? (
            <div>
              <p className='mb-2 text-xs font-medium'>
                {t('availableDevices')}
              </p>
              {loadingLinks || loadingAll ? (
                <p className='text-sm text-muted-foreground'>{t('loading')}</p>
              ) : available.length === 0 ? (
                <p className='text-sm text-muted-foreground'>
                  {t('noAvailable')}
                </p>
              ) : (
                <ul className='max-h-48 space-y-0.5 overflow-y-auto rounded-lg border border-border/60 p-2'>
                  {available.map((d) => (
                    <li
                      key={d.id}
                      className='flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50'
                    >
                      <span className='min-w-0 flex-1 truncate text-sm'>
                        {deviceLabel(d)}
                      </span>
                      <Button
                        size='sm'
                        variant='ghost'
                        className='size-7 shrink-0'
                        disabled={assigning}
                        onClick={() => handleAssign(d.id)}
                      >
                        <Plus size={14} />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
