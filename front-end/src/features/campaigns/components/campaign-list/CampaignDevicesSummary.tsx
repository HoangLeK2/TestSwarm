'use client';

import { useState } from 'react';
import { Smartphone, Users, ChevronRight, Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useCampaignDevices } from '../../hooks/use-campaigns';
import { useDeviceGroup } from '@/features/device-groups/hooks/use-device-groups';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { Badge } from '@/components/ui/badge';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AddDevicesToCampaignDialog } from '../add-devices-dialog';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { cn } from '@/lib/utils';

// ── Group-based summary ───────────────────────────────────────────────────────

function GroupDevicesSummary({
  groupId,
  triggerClassName
}: {
  groupId: string;
  triggerClassName?: string;
}) {
  const { data: group, isLoading } = useDeviceGroup(groupId);

  if (isLoading) {
    return (
      <div className='flex items-center gap-1 text-[11px] text-muted-foreground'>
        <Loader2 size={11} className='animate-spin' />
        <span>Đang tải nhóm…</span>
      </div>
    );
  }

  if (!group) return null;

  const devices = group.devices ?? [];

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          className={cn(
            'h-7 max-w-[190px] justify-start gap-1.5 px-2 text-[11px]',
            triggerClassName
          )}
          title={`${group.name} (${group.device_count})`}
        >
          <span
            className='inline-block size-2.5 shrink-0 rounded-full'
            style={{ backgroundColor: group.color }}
          />
          <span className='min-w-0 flex-1 truncate font-medium text-foreground'>
            {group.name}
          </span>
          <span className='shrink-0 text-[10px] text-muted-foreground'>
            ({group.device_count})
          </span>
          <ChevronRight size={12} className='shrink-0 text-muted-foreground' />
        </Button>
      </PopoverTrigger>
      <PopoverContent className='z-[10001] w-64 p-0' align='start'>
        {/* Header */}
        <div
          className='flex items-center gap-2 border-b px-3 py-2'
          style={{ borderLeftColor: group.color, borderLeftWidth: 3 }}
        >
          <Users size={13} className='shrink-0 text-muted-foreground' />
          <div className='min-w-0'>
            <p className='truncate text-xs font-semibold'>{group.name}</p>
            {group.description && (
              <p className='truncate text-[10px] text-muted-foreground'>
                {group.description}
              </p>
            )}
          </div>
          <Badge variant='secondary' className='ml-auto shrink-0 text-[10px]'>
            {group.device_count} thiết bị
          </Badge>
        </div>

        {/* Device list */}
        <div className='max-h-48 overflow-y-auto'>
          {devices.length === 0 ? (
            <p className='px-3 py-3 text-center text-[11px] text-muted-foreground'>
              Nhóm chưa có thiết bị nào.
            </p>
          ) : (
            devices.map((d) => (
              <div
                key={d.id}
                className='flex items-center gap-2 border-b px-3 py-1.5 last:border-b-0'
              >
                <Smartphone
                  size={11}
                  className='shrink-0 text-muted-foreground'
                />
                <div className='min-w-0'>
                  <p className='truncate text-[11px] font-medium'>
                    {d.name?.trim() || d.serial}
                  </p>
                  <p className='truncate font-mono text-[10px] text-muted-foreground'>
                    {d.serial}
                  </p>
                </div>
                {(d.brand || d.model) && (
                  <span className='ml-auto shrink-0 text-[10px] text-muted-foreground'>
                    {d.brand} {d.model}
                  </span>
                )}
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ── Explicit device list (no group) ──────────────────────────────────────────

function ExplicitDevicesSummary({
  campaignId,
  campaignName,
  triggerClassName
}: {
  campaignId: string;
  campaignName: string;
  triggerClassName?: string;
}) {
  const t = useTranslations('campaignsFeature.list');
  const { canUpdate } = useResourcePermissions('campaigns');
  const { data: devices = [] } = useCampaignDevices(campaignId);
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const buttonClassName = cn(
    'h-7 max-w-[190px] justify-start gap-1.5 px-2 text-[11px]',
    triggerClassName
  );

  if (devices.length === 0) {
    if (!canUpdate) {
      return (
        <Button
          type='button'
          variant='outline'
          size='sm'
          className={buttonClassName}
          disabled
        >
          <Smartphone size={12} className='shrink-0 text-muted-foreground' />
          {t('titleNeedDevice') ?? t('noDevices')}
        </Button>
      );
    }
    return (
      <AddDevicesToCampaignDialog
        campaignId={campaignId}
        campaignName={campaignName}
        deviceCount={0}
      >
        <Button
          type='button'
          variant='outline'
          size='sm'
          className={buttonClassName}
        >
          <Smartphone size={12} className='shrink-0 text-muted-foreground' />
          {t('titleNeedDevice') ?? t('noDevices')}
        </Button>
      </AddDevicesToCampaignDialog>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          className={buttonClassName}
          title='Xem thiết bị được gán'
        >
          <Smartphone size={12} className='shrink-0 text-muted-foreground' />
          <span className='font-medium text-foreground'>
            {devices.length} thiết bị
          </span>
          <ChevronRight size={12} className='shrink-0 text-muted-foreground' />
        </Button>
      </PopoverTrigger>
      <PopoverContent className='z-[10001] w-72 p-0' align='start'>
        <div className='flex items-center gap-2 border-b px-3 py-2'>
          <p className='text-xs font-semibold'>Thiết bị được gán</p>
          <div className='ml-auto'>
            {canUpdate ? (
              <Button
                type='button'
                size='sm'
                variant='outline'
                className='h-7 gap-1.5 px-2 text-[11px]'
                onClick={() => {
                  setAddOpen(true);
                  setOpen(false);
                }}
              >
                <Plus size={12} />
                {t('titleNeedDevice')}
              </Button>
            ) : null}
          </div>
        </div>
        <div className='max-h-48 overflow-y-auto'>
          {devices.map((d) => (
            <div
              key={d.id}
              className='flex items-center gap-2 border-b px-3 py-1.5 last:border-b-0'
            >
              <Smartphone
                size={11}
                className='shrink-0 text-muted-foreground'
              />
              <div className='min-w-0'>
                <p className='truncate text-[11px] font-medium'>
                  {d.name?.trim() || d.serial}
                </p>
                <p className='truncate font-mono text-[10px] text-muted-foreground'>
                  {d.serial}
                </p>
              </div>
            </div>
          ))}
        </div>
      </PopoverContent>

      <AddDevicesToCampaignDialog
        campaignId={campaignId}
        campaignName={campaignName}
        deviceCount={devices.length}
        open={addOpen}
        onOpenChange={setAddOpen}
      >
        {null}
      </AddDevicesToCampaignDialog>
    </Popover>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

export function CampaignDevicesSummary({
  campaignId,
  campaignName,
  targetGroupId,
  triggerClassName
}: {
  campaignId: string;
  campaignName: string;
  targetGroupId?: string | null;
  triggerClassName?: string;
}) {
  if (targetGroupId) {
    return (
      <GroupDevicesSummary
        groupId={targetGroupId}
        triggerClassName={triggerClassName}
      />
    );
  }
  return (
    <ExplicitDevicesSummary
      campaignId={campaignId}
      campaignName={campaignName}
      triggerClassName={triggerClassName}
    />
  );
}
