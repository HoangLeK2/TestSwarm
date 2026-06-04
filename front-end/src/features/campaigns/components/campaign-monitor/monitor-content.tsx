'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  useCampaignExecutions,
  useCampaignWorkflows
} from '../../hooks/use-campaigns';
import type { WorkflowInfo } from '../../types';
import { WorkflowProgressCard } from './workflow-progress-card';
import { ArtifactPanel } from './artifact-panel';
import { DlqPanel } from './dlq-panel';
import { MonitorFailureBanner } from './monitor-failure-banner';

interface Props {
  campaignId: string;
  isRunning: boolean;
}

const STATUS_FILTER_OPTIONS = [
  'all',
  'RUNNING',
  'FAILED',
  'PAUSED',
  'paused_on_error',
  'COMPLETED',
  'CANCELLED'
] as const;

function parseSerial(workflowId: string): string {
  const m = workflowId.match(/^campaign:[^:]+:device:(.+):scenario:[^:]+$/);
  return m ? m[1] : workflowId;
}

function filterWorkflows(
  workflows: WorkflowInfo[],
  statusFilter: string,
  deviceFilter: string
): WorkflowInfo[] {
  const deviceNeedle = deviceFilter.trim().toLowerCase();
  return workflows.filter((wf) => {
    if (statusFilter !== 'all' && wf.status !== statusFilter) return false;
    if (deviceNeedle) {
      const serial = parseSerial(wf.workflow_id).toLowerCase();
      if (!serial.includes(deviceNeedle)) return false;
    }
    return true;
  });
}

function MonitorSidePanels({
  campaignId,
  pollAggressive
}: {
  campaignId: string;
  pollAggressive: boolean;
}) {
  return (
    <>
      <ArtifactPanel campaignId={campaignId} pollAggressive={pollAggressive} />
      <DlqPanel campaignId={campaignId} pollAggressive={pollAggressive} />
    </>
  );
}

function MonitorWorkflowFilters({
  statusFilter,
  deviceFilter,
  onStatusChange,
  onDeviceChange
}: {
  statusFilter: string;
  deviceFilter: string;
  onStatusChange: (v: string) => void;
  onDeviceChange: (v: string) => void;
}) {
  const t = useTranslations('campaignsFeature.list');

  return (
    <div className='flex flex-wrap items-end gap-3 border-b bg-muted/10 px-6 py-3'>
      <div className='space-y-1'>
        <label className='text-[11px] text-muted-foreground'>
          {t('monitorFilterStatus')}
        </label>
        <Select value={statusFilter} onValueChange={onStatusChange}>
          <SelectTrigger className='h-8 w-[180px]'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTER_OPTIONS.map((key) => (
              <SelectItem key={key} value={key}>
                {key === 'all' ? t('monitorFilterAll') : key}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className='space-y-1'>
        <label className='text-[11px] text-muted-foreground'>
          {t('monitorFilterDevice')}
        </label>
        <Input
          className='h-8 w-[200px]'
          placeholder={t('monitorFilterDevicePlaceholder')}
          value={deviceFilter}
          onChange={(e) => onDeviceChange(e.target.value)}
        />
      </div>
    </div>
  );
}

export function MonitorContent({ campaignId, isRunning }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [deviceFilter, setDeviceFilter] = useState('');
  const { data, isLoading } = useCampaignWorkflows(campaignId, isRunning);
  const { data: executions = [] } = useCampaignExecutions(
    campaignId,
    isRunning
  );
  const workflows = data?.workflows ?? [];
  const filteredWorkflows = useMemo(
    () => filterWorkflows(workflows, statusFilter, deviceFilter),
    [workflows, statusFilter, deviceFilter]
  );

  if (isLoading) {
    return (
      <div className='flex items-center justify-center py-12 text-sm text-muted-foreground'>
        {t('loading')}
      </div>
    );
  }

  const filterBar =
    workflows.length > 0 ? (
      <MonitorWorkflowFilters
        statusFilter={statusFilter}
        deviceFilter={deviceFilter}
        onStatusChange={setStatusFilter}
        onDeviceChange={setDeviceFilter}
      />
    ) : null;

  if (!isRunning) {
    return (
      <div>
        {filterBar}
        <MonitorSidePanels
          campaignId={campaignId}
          pollAggressive={isRunning}
        />
      </div>
    );
  }

  if (!data?.temporal_available) {
    return (
      <div>
        <p className='border-b px-6 py-3 text-sm text-muted-foreground'>
          {t('monitorTemporalUnavailableMessage')}
        </p>
        {filterBar}
        <MonitorSidePanels
          campaignId={campaignId}
          pollAggressive={isRunning}
        />
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div>
        <p className='border-b px-6 py-3 text-sm text-muted-foreground'>
          {t('monitorNoRunningWorkflowsMessage')}
        </p>
        <MonitorSidePanels
          campaignId={campaignId}
          pollAggressive={isRunning}
        />
      </div>
    );
  }

  return (
    <div>
      <MonitorFailureBanner workflows={workflows} />
      {filterBar}
      <div className='divide-y'>
        {filteredWorkflows.length === 0 ? (
          <p className='px-6 py-8 text-sm text-muted-foreground'>
            {t('monitorFilterEmpty')}
          </p>
        ) : (
          filteredWorkflows.map((wf) => (
            <WorkflowProgressCard
              key={wf.workflow_id}
              wf={wf}
              campaignId={campaignId}
              executions={executions}
            />
          ))
        )}
      </div>
      <MonitorSidePanels
        campaignId={campaignId}
        pollAggressive={isRunning}
      />
    </div>
  );
}
