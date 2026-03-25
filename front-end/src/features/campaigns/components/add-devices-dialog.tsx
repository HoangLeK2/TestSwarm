'use client';

import { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { devicesApi, type DeviceOut } from '@/features/devices/services/manage-api';
import { useCampaignDevices, useAddDeviceToCampaign, useRemoveDeviceFromCampaign } from '../hooks/use-campaigns';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Checkbox } from '@/components/ui/checkbox';
import { Smartphone, Plus, CheckCheck, X } from 'lucide-react';
import { useTranslations } from 'next-intl';

function deviceLabel(d: { serial: string; name?: string | null }) {
  return d.name?.trim() || d.serial || '—';
}

export function AddDevicesToCampaignDialog({
  campaignId,
  campaignName,
  deviceCount,
  children
}: {
  campaignId: string;
  campaignName: string;
  deviceCount: number;
  children?: React.ReactNode;
}) {
  const t = useTranslations('campaignsFeature.addDevices');
  const [open, setOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const { data: campaignDevices = [], isLoading: loadingCampaign } = useCampaignDevices(campaignId);
  const { data: allDevices = [], isLoading: loadingAll } = useQuery({
    queryKey: ['devices'],
    queryFn: () => devicesApi.list()
  });
  const { mutate: addDevice, mutateAsync: addDeviceAsync, isPending: adding } = useAddDeviceToCampaign();
  const { mutate: removeDevice, isPending: removing } = useRemoveDeviceFromCampaign();

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
  }, [campaignId, selectedIds, addDeviceAsync]);

  const addOne = useCallback(
    (deviceId: string) => {
      addDevice({ campaignId, deviceId });
    },
    [campaignId, addDevice]
  );

  const onOpenChange = useCallback(
    (v: boolean) => {
      setOpen(v);
      if (!v) setSelectedIds(new Set());
    },
    []
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        {children ?? (
          <Button variant="outline" size="sm" className="text-xs gap-1">
            <Smartphone size={12} />
            {t('trigger', { count: deviceCount })}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-lg z-[1000]">
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className="text-sm text-muted-foreground">{campaignName}</p>
        </DialogHeader>
        <div className="space-y-4 pt-2">
          {/* Đã có trong campaign — biết rõ kết nối với thiết bị nào */}
          {campaignDevices.length > 0 && (
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <p className="mb-2 text-xs font-medium text-foreground">
                {t('existingDevices', { count: campaignDevices.length })}
              </p>
              <ul className="max-h-28 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                {campaignDevices.map((d) => (
                  <li key={d.id} className="flex items-center gap-2 rounded py-0.5 font-mono">
                    <Smartphone className="size-3 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">
                      {deviceLabel(d)}
                      {d.name?.trim() && d.serial && d.serial !== d.name.trim() && (
                        <span className="text-muted-foreground/70"> · {d.serial}</span>
                      )}
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="size-6 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      disabled={removing}
                      onClick={() => removeDevice({ campaignId, deviceId: d.id })}
                      title={t('removeTitle')}
                    >
                      <X size={12} />
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Có thể thêm: chọn 1 hoặc chọn hết */}
          <div>
            <p className="mb-2 text-xs font-medium text-foreground">{t('addSection')}</p>
            {loadingCampaign || loadingAll ? (
              <p className="text-sm text-muted-foreground">{t('loading')}</p>
            ) : available.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('noAvailable')}
              </p>
            ) : (
              <>
                <div className="mb-2 flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-xs gap-1"
                    onClick={selectAll}
                  >
                    <CheckCheck size={12} />
                    {t('selectAll', { count: available.length })}
                  </Button>
                  {selectedIds.size > 0 && (
                    <>
                      <Button
                        type="button"
                        variant="default"
                        size="sm"
                        className="text-xs"
                        disabled={adding}
                        onClick={addSelected}
                      >
                        {t('addSelected', { count: selectedIds.size })}
                      </Button>
                      <Button type="button" variant="ghost" size="sm" className="text-xs" onClick={clearSelection}>
                        {t('clearSelection')}
                      </Button>
                    </>
                  )}
                </div>
                <ul className="max-h-56 space-y-0.5 overflow-y-auto rounded-lg border border-border/60 p-2">
                  {available.map((d) => (
                    <li
                      key={d.id}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50"
                    >
                      <Checkbox
                        checked={selectedIds.has(d.id)}
                        onCheckedChange={() => toggleOne(d.id)}
                        aria-label={t('selectOneAria', { name: deviceLabel(d) })}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm" title={d.serial}>
                        {deviceLabel(d)}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="size-7 shrink-0"
                        disabled={adding}
                        onClick={() => addOne(d.id)}
                        title={t('addOneTitle')}
                      >
                        <Plus size={14} />
                      </Button>
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-xs text-muted-foreground">
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
