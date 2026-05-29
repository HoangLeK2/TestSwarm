'use client';

import { useCampaignWorkflows } from '../../hooks/use-campaigns';
import { useTranslations } from 'next-intl';
import { WorkflowProgressCard } from './workflow-progress-card';
import { ArtifactPanel } from './artifact-panel';
import { DlqPanel } from './dlq-panel';

interface Props {
  campaignId: string;
  isRunning: boolean;
}

function MonitorSidePanels({ campaignId }: { campaignId: string }) {
  return (
    <>
      <ArtifactPanel campaignId={campaignId} />
      <DlqPanel campaignId={campaignId} />
    </>
  );
}

export function MonitorContent({ campaignId, isRunning }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data, isLoading } = useCampaignWorkflows(campaignId, isRunning);
  const workflows = data?.workflows ?? [];

  if (isLoading) {
    return (
      <div className='flex items-center justify-center py-12 text-sm text-muted-foreground'>
        {t('loading')}
      </div>
    );
  }

  if (!isRunning) {
    return <MonitorSidePanels campaignId={campaignId} />;
  }

  if (!data?.temporal_available) {
    return (
      <div>
        <p className='border-b px-6 py-3 text-sm text-muted-foreground'>
          {t('monitorTemporalUnavailableMessage')}
        </p>
        <MonitorSidePanels campaignId={campaignId} />
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div>
        <p className='border-b px-6 py-3 text-sm text-muted-foreground'>
          {t('monitorNoRunningWorkflowsMessage')}
        </p>
        <MonitorSidePanels campaignId={campaignId} />
      </div>
    );
  }

  return (
    <div>
      <div className='divide-y'>
        {workflows.map((wf) => (
          <WorkflowProgressCard
            key={wf.workflow_id}
            wf={wf}
            campaignId={campaignId}
          />
        ))}
      </div>
      <MonitorSidePanels campaignId={campaignId} />
    </div>
  );
}
