'use client';

import { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  devicesApi,
  type DeviceOut
} from '@/features/devices/services/manage-api';
import {
  useCampaignDevices,
  useAddDeviceToCampaign,
  useRemoveDeviceFromCampaign
} from '../hooks/use-campaigns';
import {
  useDeviceGroup,
  useDeviceGroups
} from '@/features/device-groups/hooks/use-device-groups';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogDescription,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Smartphone, Plus, CheckCheck, X, Layers } from 'lucide-react';
import { useTranslations } from 'next-intl';

function deviceLabel(d: { serial: string; name?: string | null }) {
  return d.name?.trim() || d.serial || '—';
}

export function AddDevicesToCampaignDialog({
  campaignId,
  campaignName,
  deviceCount,
  children,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange
}: {
  campaignId: string;
  campaignName: string;
  deviceCount: number;
  children?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations('campaignsFeature.addDevices');
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = controlledOnOpenChange ?? setUncontrolledOpen;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pickedGroupId, setPickedGroupId] = useState<string>('');
  const [bulkAdding, setBulkAdding] = useState(false);

  const { data: campaignDevices = [], isLoading: loadingCampaign } =
    useCampaignDevices(campaignId, open);
  const { data: allDevices = [], isLoading: loadingAll } = useQuery({
    queryKey: ['devices'],
    queryFn: () => devicesApi.list(),
    enabled: open
  });
  const { data: groups = [] } = useDeviceGroups();
  const { data: pickedGroup } = useDeviceGroup(pickedGroupId);
  const {
    mutate: addDevice,
    mutateAsync: addDeviceAsync,
    isPending: adding
  } = useAddDeviceToCampaign();
  const { mutate: removeDevice, isPending: removing } =
    useRemoveDeviceFromCampaign();

  const addedIds = new Set(campaignDevices.map((d) => d.id));
  const available: DeviceOut[] = allDevices.filter((d) => !addedIds.has(d.id));

  const toggleOne = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    if (available.length === 0) return;
    setSelectedIds(new Set(available.map((d) => d.id)));
  }, [available]);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const addSelected = useCallback(async () => {
    if (selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    try {
      for (const deviceId of ids) {
        await addDeviceAsync({ campaignId, deviceId });
      }
      setSelectedIds(new Set());
      if (ids.length > 1) toast.success(t('addedMany', { count: ids.length }));
    } catch {
      toast.error(t('addError'));
    }
  }, [campaignId, selectedIds, addDeviceAsync, t]);

  const addOne = useCallback(
    (deviceId: string) => {
      addDevice({ campaignId, deviceId });
    },
    [campaignId, addDevice]
  );

  const onOpenChange = useCallback(
    (v: boolean) => {
      setOpen(v);
      if (!v) {
        setSelectedIds(new Set());
        setPickedGroupId('');
      }
    },
    [setOpen]
  );

  const groupNewDeviceIds = (pickedGroup?.devices ?? [])
    .map((d) => d.id)
    .filter((id) => !addedIds.has(id));

  const addWholeGroup = useCallback(async () => {
    if (groupNewDeviceIds.length === 0) return;
    setBulkAdding(true);
    let added = 0;
    let failed = 0;
    for (const deviceId of groupNewDeviceIds) {
      try {
        await addDeviceAsync({ campaignId, deviceId });
        added += 1;
      } catch {
        failed += 1;
      }
    }
    setBulkAdding(false);
    if (added > 0)
      toast.success(
        `Đã thêm ${added} thiết bị từ nhóm "${pickedGroup?.name ?? ''}"`
      );
    if (failed > 0) toast.error(`${failed} thiết bị thêm thất bại`);
    setPickedGroupId('');
  }, [campaignId, groupNewDeviceIds, addDeviceAsync, pickedGroup?.name]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {children !== null && (
        <DialogTrigger asChild>
          {children ?? (
            <Button variant='outline' size='sm' className='gap-1 text-xs'>
              <Smartphone size={12} />
              {t('trigger', { count: deviceCount })}
            </Button>
          )}
        </DialogTrigger>
      )}
      <DialogContent className='z-[1000] max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>{campaignName}</DialogDescription>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          {/* Đã có trong campaign — biết rõ kết nối với thiết bị nào */}
          {campaignDevices.length > 0 && (
            <div className='rounded-lg border border-border/60 bg-muted/20 p-3'>
              <p className='mb-2 text-xs font-medium text-foreground'>
                {t('existingDevices', { count: campaignDevices.length })}
              </p>
              <ul className='max-h-28 space-y-1 overflow-y-auto text-xs text-muted-foreground'>
                {campaignDevices.map((d) => (
                  <li
                    key={d.id}
                    className='flex items-center gap-2 rounded py-0.5 font-mono'
                  >
                    <Smartphone className='size-3 shrink-0' />
                    <span className='min-w-0 flex-1 truncate'>
                      {deviceLabel(d)}
                      {d.name?.trim() &&
                        d.serial &&
                        d.serial !== d.name.trim() && (
                          <span className='text-muted-foreground/70'>
                            {' '}
                            · {d.serial}
                          </span>
                        )}
                    </span>
                    <Button
                      type='button'
                      size='sm'
                      variant='ghost'
                      className='size-6 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive'
                      disabled={removing}
                      onClick={() =>
                        removeDevice({ campaignId, deviceId: d.id })
                      }
                      title={t('removeTitle')}
                    >
                      <X size={12} />
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Thêm cả nhóm thiết bị */}
          <div className='rounded-lg border border-primary/20 bg-primary/[0.04] p-3'>
            <div className='mb-2 flex items-center gap-1.5'>
              <Layers size={13} className='text-primary' />
              <p className='text-xs font-semibold text-foreground'>
                Thêm cả nhóm thiết bị
              </p>
            </div>
            {groups.length === 0 ? (
              <p className='text-xs text-muted-foreground'>
                Chưa có nhóm thiết bị nào. Tạo nhóm tại trang{' '}
                <span className='font-medium text-foreground'>
                  Device Groups
                </span>{' '}
                trước khi dùng tính năng này.
              </p>
            ) : (
              <div className='flex flex-wrap items-center gap-2'>
                <div className='min-w-[180px] flex-1'>
                  <Select
                    value={pickedGroupId || '_none'}
                    onValueChange={(v) =>
                      setPickedGroupId(v === '_none' ? '' : v)
                    }
                  >
                    <SelectTrigger className='h-9 text-sm'>
                      <SelectValue placeholder='Chọn nhóm…' />
                    </SelectTrigger>
                    <SelectContent className='z-[10001]'>
                      <SelectItem value='_none'>
                        <span className='text-muted-foreground'>
                          — Chọn nhóm —
                        </span>
                      </SelectItem>
                      {groups.map((g) => (
                        <SelectItem key={g.id} value={g.id}>
                          <span className='flex items-center gap-2'>
                            <span
                              className='inline-block size-3 shrink-0 rounded-full'
                              style={{ backgroundColor: g.color }}
                            />
                            <span>{g.name}</span>
                            <span className='text-muted-foreground'>
                              ({g.device_count})
                            </span>
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type='button'
                  size='sm'
                  className='h-9 gap-1.5 text-xs'
                  disabled={
                    !pickedGroupId ||
                    bulkAdding ||
                    adding ||
                    groupNewDeviceIds.length === 0
                  }
                  onClick={addWholeGroup}
                >
                  <Plus size={13} />
                  {bulkAdding
                    ? 'Đang thêm…'
                    : pickedGroupId
                      ? `Thêm ${groupNewDeviceIds.length} thiết bị`
                      : 'Thêm cả nhóm'}
                </Button>
              </div>
            )}
            {pickedGroupId && pickedGroup && groupNewDeviceIds.length === 0 && (
              <p className='mt-2 text-xs text-muted-foreground'>
                Tất cả thiết bị trong nhóm{' '}
                <span className='font-medium text-foreground'>
                  {pickedGroup.name}
                </span>{' '}
                đã có trong campaign.
              </p>
            )}
          </div>

          {/* Có thể thêm: chọn 1 hoặc chọn hết */}
          <div>
            <p className='mb-2 text-xs font-medium text-foreground'>
              {t('addSection')}
            </p>
            {loadingCampaign || loadingAll ? (
              <p className='text-sm text-muted-foreground'>{t('loading')}</p>
            ) : available.length === 0 ? (
              <p className='text-sm text-muted-foreground'>
                {t('noAvailable')}
              </p>
            ) : (
              <>
                <div className='mb-2 flex items-center gap-2'>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    className='gap-1 text-xs'
                    onClick={selectAll}
                  >
                    <CheckCheck size={12} />
                    {t('selectAll', { count: available.length })}
                  </Button>
                  {selectedIds.size > 0 && (
                    <>
                      <Button
                        type='button'
                        variant='default'
                        size='sm'
                        className='text-xs'
                        disabled={adding}
                        onClick={addSelected}
                      >
                        {t('addSelected', { count: selectedIds.size })}
                      </Button>
                      <Button
                        type='button'
                        variant='ghost'
                        size='sm'
                        className='text-xs'
                        onClick={clearSelection}
                      >
                        {t('clearSelection')}
                      </Button>
                    </>
                  )}
                </div>
                <ul className='max-h-56 space-y-0.5 overflow-y-auto rounded-lg border border-border/60 p-2'>
                  {available.map((d) => (
                    <li
                      key={d.id}
                      className='flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50'
                    >
                      <Checkbox
                        checked={selectedIds.has(d.id)}
                        onCheckedChange={() => toggleOne(d.id)}
                        aria-label={t('selectOneAria', {
                          name: deviceLabel(d)
                        })}
                      />
                      <span
                        className='min-w-0 flex-1 truncate text-sm'
                        title={d.serial}
                      >
                        {deviceLabel(d)}
                      </span>
                      <Button
                        size='sm'
                        variant='ghost'
                        className='size-7 shrink-0'
                        disabled={adding}
                        onClick={() => addOne(d.id)}
                        title={t('addOneTitle')}
                      >
                        <Plus size={14} />
                      </Button>
                    </li>
                  ))}
                </ul>
                <p className='mt-1.5 text-xs text-muted-foreground'>
                  {t('helper')}
                </p>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
