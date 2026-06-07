'use client';

import { useTranslations } from 'next-intl';
import { ArrowLeft, Trash2, Smartphone } from 'lucide-react';
import {
  useDeviceGroup,
  useRemoveDeviceFromGroup
} from '../hooks/use-device-groups';
import { AddDevicesToGroupDialog } from './add-devices-to-group-dialog';
import { EditDeviceGroupDialog } from './edit-device-group-dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

interface Props {
  groupId: string;
  onBack: () => void;
}

export function DeviceGroupDetail({ groupId, onBack }: Props) {
  const t = useTranslations('deviceGroupsFeature.detail');
  const { data: group, isLoading } = useDeviceGroup(groupId);
  const removeMutation = useRemoveDeviceFromGroup();
  const perms = useResourcePermissions('device-groups');

  if (isLoading) {
    return <p className='text-sm text-muted-foreground'>{t('loading')}</p>;
  }

  if (!group) {
    return <p className='text-sm text-destructive'>{t('notFound')}</p>;
  }

  return (
    <div className='space-y-6'>
      <div className='flex items-center gap-3'>
        <Button size='icon' variant='ghost' onClick={onBack}>
          <ArrowLeft size={18} />
        </Button>
        <div
          className='size-5 rounded-full'
          style={{ backgroundColor: group.color }}
        />
        <h2 className='text-lg font-semibold'>{group.name}</h2>
        <Badge variant='secondary'>{group.device_count} devices</Badge>
        {perms.canUpdate ? <EditDeviceGroupDialog group={group} /> : null}
      </div>

      {group.description && (
        <p className='text-sm text-muted-foreground'>{group.description}</p>
      )}

      <div className='flex items-center justify-between'>
        <h3 className='text-sm font-medium'>{t('devicesTitle')}</h3>
        {perms.canUpdate ? (
          <AddDevicesToGroupDialog groupId={groupId} />
        ) : null}
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
                {device.name || device.serial}
              </p>
              <p className='text-xs text-muted-foreground'>
                {device.brand} {device.model} &middot; Android{' '}
                {device.android_version}
              </p>
            </div>
            {perms.canUpdate ? (
              <Button
                size='icon'
                variant='ghost'
                className='size-8 text-destructive hover:text-destructive'
                disabled={removeMutation.isPending}
                onClick={() =>
                  removeMutation.mutate({ groupId, deviceId: device.id })
                }
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
