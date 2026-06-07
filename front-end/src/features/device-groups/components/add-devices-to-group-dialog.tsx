'use client';

import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useDevices } from '@/features/devices/hooks/use-devices';
import {
  useAddDevicesToGroup,
  useDeviceGroup
} from '../hooks/use-device-groups';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import type { DeviceOut } from '@/features/devices/services/manage-api';

interface Props {
  groupId: string;
}

export function AddDevicesToGroupDialog({ groupId }: Props) {
  const t = useTranslations('deviceGroupsFeature.addDevicesDialog');
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const { data: devices } = useDevices();
  const { data: group, isLoading: groupLoading } = useDeviceGroup(groupId, {
    enabled: open
  });
  const { mutate, isPending } = useAddDevicesToGroup();

  const existingDeviceIds = useMemo(
    () => new Set((group?.devices ?? []).map((d) => d.id)),
    [group?.devices]
  );

  const available = useMemo(
    () => (devices ?? []).filter((d) => !existingDeviceIds.has(d.id)),
    [devices, existingDeviceIds]
  );

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSubmit = () => {
    if (!selected.length) return;
    mutate(
      { groupId, deviceIds: selected },
      {
        onSuccess: () => {
          setSelected([]);
          setOpen(false);
        }
      }
    );
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) setSelected([]);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          <Plus size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <div className='max-h-64 space-y-2 overflow-y-auto pt-2'>
          {groupLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {!groupLoading && available.length === 0 && (
            <p className='text-sm text-muted-foreground'>{t('noDevices')}</p>
          )}
          {!groupLoading &&
            available.map((d: DeviceOut) => (
              <label
                key={d.id}
                className='flex cursor-pointer items-center gap-3 rounded-md border p-3 hover:bg-muted/50'
              >
                <Checkbox
                  checked={selected.includes(d.id)}
                  onCheckedChange={() => toggle(d.id)}
                />
                <div className='min-w-0 flex-1'>
                  <p className='truncate text-sm font-medium'>
                    {d.name || d.serial}
                  </p>
                  <p className='text-xs text-muted-foreground'>
                    {d.brand} {d.model}
                  </p>
                </div>
              </label>
            ))}
        </div>
        <Button
          onClick={handleSubmit}
          disabled={isPending || groupLoading || selected.length === 0}
          className='w-full'
        >
          {isPending ? t('adding') : t('submit', { count: selected.length })}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
