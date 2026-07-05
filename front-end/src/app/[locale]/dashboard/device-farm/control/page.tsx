'use client';

import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { ControlRecordView } from '@/features/devices/components/control-record-view';

export default function DeviceControlRecordPage() {
  const t = useTranslations('devicesControlRecord');
  const searchParams = useSearchParams();
  const serial = searchParams.get('serial') ?? undefined;
  const campaignId = searchParams.get('campaignId') ?? undefined;
  const scenarioId = searchParams.get('scenarioId') ?? undefined;
  const templateId = searchParams.get('templateId') ?? undefined;
  const orgScenarioId = searchParams.get('orgScenarioId') ?? undefined;
  const returnTo = searchParams.get('returnTo') ?? undefined;

  return (
    <div>
      <h1 className='text-xl font-semibold'>{t('pageTitle')}</h1>
      <ControlRecordView
        initialSerial={serial}
        initialCampaignId={campaignId}
        initialScenarioId={scenarioId}
        initialTemplateId={templateId}
        initialOrgScenarioId={orgScenarioId}
        returnTo={returnTo}
      />
    </div>
  );
}
