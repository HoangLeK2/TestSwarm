'use client';

import { Smartphone, Users, ChevronRight } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useCampaignDevices } from '../../hooks/use-campaigns';
import { useDeviceGroup } from '@/features/device-groups/hooks/use-device-groups';
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover';
import { Badge } from '@/components/ui/badge';
import { Loader2 } from 'lucide-react';

// ── Group-based summary ───────────────────────────────────────────────────────

function GroupDevicesSummary({ groupId }: { groupId: string }) {
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
        <button
          type='button'
          className='flex items-center gap-1.5 rounded text-left hover:opacity-80'
        >
          <span
            className='inline-block size-2.5 shrink-0 rounded-full'
            style={{ backgroundColor: group.color }}
          />
          <span className='max-w-[120px] truncate text-[11px] font-medium text-foreground'>
            {group.name}
          </span>
          <span className='shrink-0 text-[10px] text-muted-foreground'>
            ({group.device_count})
          </span>
          <ChevronRight size={10} className='shrink-0 text-muted-foreground' />
        </button>
      </PopoverTrigger>
      <PopoverContent className='w-64 p-0 z-[10001]' align='start'>
        {/* Header */}
        <div
          className='flex items-center gap-2 border-b px-3 py-2'
          style={{ borderLeftColor: group.color, borderLeftWidth: 3 }}
        >
          <Users size={13} className='shrink-0 text-muted-foreground' />
          <div className='min-w-0'>
            <p className='truncate text-xs font-semibold'>{group.name}</p>
            {group.description && (
              <p className='truncate text-[10px] text-muted-foreground'>{group.description}</p>
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
                <Smartphone size={11} className='shrink-0 text-muted-foreground' />
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

function ExplicitDevicesSummary({ campaignId }: { campaignId: string }) {
  const t = useTranslations('campaignsFeature.list');
  const { data: devices = [] } = useCampaignDevices(campaignId);

  if (devices.length === 0) {
    return <span className='text-[11px] text-muted-foreground'>{t('noDevices')}</span>;
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type='button'
          className='flex items-center gap-1.5 rounded text-left hover:opacity-80'
        >
          <Smartphone size={12} className='shrink-0 text-muted-foreground' />
          <span className='text-[11px] font-medium text-foreground'>
            {devices.length} thiết bị
          </span>
          <ChevronRight size={10} className='shrink-0 text-muted-foreground' />
        </button>
      </PopoverTrigger>
      <PopoverContent className='w-60 p-0 z-[10001]' align='start'>
        <div className='border-b px-3 py-2'>
          <p className='text-xs font-semibold'>Thiết bị được gán</p>
        </div>
        <div className='max-h-48 overflow-y-auto'>
          {devices.map((d) => (
            <div
              key={d.id}
              className='flex items-center gap-2 border-b px-3 py-1.5 last:border-b-0'
            >
              <Smartphone size={11} className='shrink-0 text-muted-foreground' />
              <div className='min-w-0'>
                <p className='truncate text-[11px] font-medium'>
                  {d.name?.trim() || d.serial}
                </p>
                <p className='truncate font-mono text-[10px] text-muted-foreground'>{d.serial}</p>
              </div>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

export function CampaignDevicesSummary({
  campaignId,
  targetGroupId,
}: {
  campaignId: string;
  targetGroupId?: string | null;
}) {
  if (targetGroupId) {
    return <GroupDevicesSummary groupId={targetGroupId} />;
  }
  return <ExplicitDevicesSummary campaignId={campaignId} />;
}
