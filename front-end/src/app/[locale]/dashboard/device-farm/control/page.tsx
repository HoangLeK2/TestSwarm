'use client';

import { useSearchParams } from 'next/navigation';
import { ControlRecordView } from '@/features/devices/components/control-record-view';

export default function DeviceControlRecordPage() {
  const searchParams = useSearchParams();
  const serial = searchParams.get('serial') ?? undefined;
  const campaignId = searchParams.get('campaignId') ?? undefined;
  const scenarioId = searchParams.get('scenarioId') ?? undefined;
  const templateId = searchParams.get('templateId') ?? undefined;
  const orgScenarioId = searchParams.get('orgScenarioId') ?? undefined;
  const returnTo = searchParams.get('returnTo') ?? undefined;

  return (
    <ControlRecordView
      initialSerial={serial}
      initialCampaignId={campaignId}
      initialScenarioId={scenarioId}
      initialTemplateId={templateId}
      initialOrgScenarioId={orgScenarioId}
      returnTo={returnTo}
    />
  );
}
