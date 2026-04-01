'use client';

import { useCampaignWorkflows } from '../../hooks/use-campaigns';
import { WorkflowProgressCard } from './workflow-progress-card';

interface Props {
  campaignId: string;
}

export function MonitorContent({ campaignId }: Props) {
  const { data, isLoading } = useCampaignWorkflows(campaignId, true);
  const workflows = data?.workflows ?? [];

  if (!data?.temporal_available) {
    return (
      <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
        Temporal chưa được kích hoạt — không thể theo dõi từng bước.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
        Đang tải...
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className='flex items-center justify-center py-12 text-xs text-muted-foreground'>
        Chưa có workflow nào đang chạy.
      </div>
    );
  }

  return (
    <div className='max-h-[70vh] overflow-y-auto divide-y'>
      {workflows.map((wf) => (
        <WorkflowProgressCard key={wf.workflow_id} wf={wf} />
      ))}
    </div>
  );
}
