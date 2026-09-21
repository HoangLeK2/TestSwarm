'use client';

import { useTranslations } from 'next-intl';
import { ArrowLeft, Trash2, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import {
  useDeviceGroup,
  useRemoveDeviceFromGroup
} from '../hooks/use-device-groups';
import { AddDevicesToGroupDialog } from './add-devices-to-group-dialog';
import { EditDeviceGroupDialog } from './edit-device-group-dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { useConfirm } from '@/providers/modal-provider';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  deviceDisplayName,
  deviceModelLabel,
  deviceSecondarySerial
} from '@/features/devices/lib/device-display-name';

interface Props {
  groupId: string;
  onBack: () => void;
}

export function DeviceGroupDetail({ groupId, onBack }: Props) {
  const t = useTranslations('deviceGroupsFeature.detail');
  const { data: group, isLoading, error } = useDeviceGroup(groupId);
  const removeMutation = useRemoveDeviceFromGroup();
  const perms = useResourcePermissions('device-groups');
  const confirm = useConfirm();

  if (isLoading) {
    return <p className='text-sm text-muted-foreground'>{t('loading')}</p>;
  }

  if (error) {
    return (
      <p className='text-sm text-destructive'>
        {formatFarmApiError(error, t('loadError'))}
      </p>
    );
  }

  if (!group) {
    return <p className='text-sm text-destructive'>{t('notFound')}</p>;
  }

  const removeDevice = async (
    device: NonNullable<typeof group.devices>[number]
  ) => {
    const deviceName = deviceDisplayName(device);
    const ok = await confirm({
      description: t('confirmRemoveDevice', {
        device: deviceName,
        group: group.name
      }),
      confirmText: t('removeConfirm'),
      cancelText: t('removeCancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    if (!ok) return;
    removeMutation.mutate(
      { groupId, deviceId: device.id },
      {
        onSuccess: () =>
          toast.success(t('removeSuccess', { device: deviceName })),
        onError: (err) => {
          toast.error(formatFarmApiError(err, t('removeFailed')));
        }
      }
    );
  };

  return (
    <div className='space-y-6'>
      <div className='flex items-center gap-3'>
        <Button
          size='icon'
          variant='ghost'
          onClick={onBack}
          aria-label={t('backAction')}
        >
          <ArrowLeft size={18} />
        </Button>
        <div
          className='size-5 rounded-full'
          style={{ backgroundColor: group.color }}
        />
        <h2 className='text-lg font-semibold'>{group.name}</h2>
        <Badge variant='secondary'>
          {t('deviceCount', { count: group.device_count })}
        </Badge>
        {perms.canUpdate ? <EditDeviceGroupDialog group={group} /> : null}
      </div>

      {group.description && (
        <p className='text-sm text-muted-foreground'>{group.description}</p>
      )}

      <div className='flex items-center justify-between'>
        <h3 className='text-sm font-medium'>{t('devicesTitle')}</h3>
        {perms.canUpdate ? <AddDevicesToGroupDialog groupId={groupId} /> : null}
      </div>

      {(!group.devices || group.devices.length === 0) && (
        <div className='rounded-xl border border-dashed border-border bg-muted/20 p-10 text-center'>
          <Smartphone className='mx-auto mb-3 size-10 text-muted-foreground/80' />
          <p className='text-sm text-muted-foreground'>{t('noDevices')}</p>
        </div>
      )}

      <div className='space-y-2'>
        {(group.devices ?? []).map((device) => (
          <div
            key={device.id}
            className='flex items-center justify-between rounded-lg border p-3'
          >
            <div className='min-w-0 flex-1'>
              <p className='truncate text-sm font-medium'>
                {deviceDisplayName(device)}
              </p>
              <div className='space-y-0.5 text-xs text-muted-foreground'>
                {deviceSecondarySerial(device) ? (
                  <p className='truncate'>
                    {t('serialLabel', {
                      serial: deviceSecondarySerial(device)
                    })}
                  </p>
                ) : null}
                <p className='truncate'>
                  {[
                    deviceModelLabel(device),
                    `Android ${device.android_version}`
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>
            </div>
            {perms.canUpdate ? (
              <Button
                size='icon'
                variant='ghost'
                className='size-8 text-destructive hover:text-destructive'
                disabled={removeMutation.isPending}
                onClick={() => void removeDevice(device)}
                aria-label={t('removeDeviceAction', {
                  device: deviceDisplayName(device)
                })}
              >
                <Trash2 size={14} />
              </Button>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
