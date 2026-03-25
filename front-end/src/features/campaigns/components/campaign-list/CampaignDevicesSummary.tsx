'use client';

import { Smartphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useCampaignDevices } from '../../hooks/use-campaigns';

function deviceLabel(d: { serial: string; name?: string | null }) {
  return d.name?.trim() || d.serial || '—';
}

export function CampaignDevicesSummary({ campaignId }: { campaignId: string }) {
  const t = useTranslations('campaignsFeature.list');
  const { data: devices = [] } = useCampaignDevices(campaignId);

  return (
    <div className='flex flex-col gap-0.5 text-[11px] text-muted-foreground'>
      <div className='flex items-center gap-1.5 text-xs text-foreground'>
        <Smartphone className='size-3.5' />
        <span>{t('devicesInCampaign', { count: devices.length })}</span>
      </div>

      {devices.length === 0 ? (
        <span>{t('noDevices')}</span>
      ) : (
        <>
          {devices.slice(0, 3).map((d) => (
            <div
              key={d.id}
              className='truncate font-mono'
              title={`${d.serial} ${d.name || ''}`}
            >
              {deviceLabel(d)}
            </div>
          ))}

          {devices.length > 3 && <span>{t('otherDevices', { count: devices.length - 3 })}</span>}
        </>
      )}
    </div>
  );
}

