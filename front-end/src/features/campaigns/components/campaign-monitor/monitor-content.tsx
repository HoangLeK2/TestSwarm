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

export function MonitorContent({ campaignId, isRunning }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data, isLoading } = useCampaignWorkflows(campaignId, isRunning);
  const workflows = data?.workflows ?? [];

  if (isLoading) {
    return (
      <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
        {t('loading')}
      </div>
    );
  }

  if (!isRunning) {
    return (
      <div>
        <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
          {t('monitorNotRunningMessage')}
        </div>
        <ArtifactPanel campaignId={campaignId} />
        <DlqPanel />
      </div>
    );
  }

  if (!data?.temporal_available) {
    return (
      <div>
        <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
          {t('monitorTemporalUnavailableMessage')}
        </div>
        <ArtifactPanel campaignId={campaignId} />
        <DlqPanel />
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div>
        <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
          {t('monitorNoRunningWorkflowsMessage')}
        </div>
        <ArtifactPanel campaignId={campaignId} />
        <DlqPanel />
      </div>
    );
  }

  return (
    <div>
      <div className='max-h-[54vh] overflow-y-auto divide-y'>
        {workflows.map((wf) => (
          <WorkflowProgressCard key={wf.workflow_id} wf={wf} campaignId={campaignId} />
        ))}
      </div>
      <ArtifactPanel campaignId={campaignId} />
      <DlqPanel />
    </div>
  );
}
