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
  useCampaign,
  useCampaignExecutions,
  useCampaignWorkflows
} from '../../hooks/use-campaigns';
import type { WorkflowInfo } from '../../types';
import { WorkflowProgressCard } from './workflow-progress-card';
import { resolveExecutionIdForWorkflow } from '../../lib/execution-event-utils';
import { ArtifactPanel } from './artifact-panel';
import { DlqPanel } from './dlq-panel';
import { MonitorFailureBanner } from './monitor-failure-banner';
import { Z_CAMPAIGN_MONITOR_FLOATING } from '@/lib/z-index';
import { isContinuousCrawl } from '../../lib/continuous-crawl-monitor';
import { ContinuousCrawlDashboard } from './continuous-crawl-dashboard';

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
    <div className='flex w-full flex-col border-t md:flex-row md:divide-x'>
      <div className='min-w-0 overflow-hidden border-b md:w-[46%] md:shrink-0 md:border-b-0'>
        <ArtifactPanel
          campaignId={campaignId}
          pollAggressive={pollAggressive}
          variant='split'
        />
      </div>
      <div className='min-w-0 flex-1 overflow-hidden'>
        <DlqPanel campaignId={campaignId} pollAggressive={pollAggressive} />
      </div>
    </div>
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
          <SelectContent style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}>
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
  const { data: campaign, isLoading: isCampaignLoading } =
    useCampaign(campaignId);
  const continuous = isContinuousCrawl(campaign?.vars ?? campaign?.variables);
  const pollStandardMonitor = !!campaign && isRunning && !continuous;
  const { data, isLoading } = useCampaignWorkflows(
    campaignId,
    pollStandardMonitor
  );
  const { data: executions = [] } = useCampaignExecutions(
    campaignId,
    pollStandardMonitor
  );
  const executionsById = useMemo(
    () => new Map(executions.map((execution) => [execution.id, execution])),
    [executions]
  );
  const workflows = useMemo(() => data?.workflows ?? [], [data?.workflows]);
  const filteredWorkflows = useMemo(
    () => filterWorkflows(workflows, statusFilter, deviceFilter),
    [workflows, statusFilter, deviceFilter]
  );

  if (isCampaignLoading || (!continuous && isRunning && isLoading)) {
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
  const crawlDashboard = (
    <ContinuousCrawlDashboard campaignId={campaignId} enabled={continuous} />
  );

  if (continuous) {
    return (
      <div>
        {crawlDashboard}
        <MonitorSidePanels campaignId={campaignId} pollAggressive={isRunning} />
      </div>
    );
  }

  if (isRunning && data && !data.temporal_available && workflows.length === 0) {
    return (
      <div>
        {crawlDashboard}
        <p className='border-b px-6 py-3 text-sm text-muted-foreground'>
          {t('monitorTemporalUnavailableMessage')}
        </p>
        {filterBar}
        <MonitorSidePanels campaignId={campaignId} pollAggressive={isRunning} />
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div>
        {crawlDashboard}
        <p className='border-b px-6 py-3 text-sm text-muted-foreground'>
          {t('monitorNoRunningWorkflowsMessage')}
        </p>
        <MonitorSidePanels campaignId={campaignId} pollAggressive={isRunning} />
      </div>
    );
  }

  return (
    <div>
      {crawlDashboard}
      <MonitorFailureBanner workflows={workflows} />
      {filterBar}
      <div className='divide-y'>
        {filteredWorkflows.length === 0 ? (
          <p className='px-6 py-8 text-sm text-muted-foreground'>
            {t('monitorFilterEmpty')}
          </p>
        ) : (
          filteredWorkflows.map((wf) => {
            const executionId =
              wf.execution_id ||
              resolveExecutionIdForWorkflow(wf.workflow_id, executions) ||
              '';
            return (
              <WorkflowProgressCard
                key={wf.workflow_id}
                wf={wf}
                campaignId={campaignId}
                execution={executionsById.get(executionId)}
              />
            );
          })
        )}
      </div>
      <MonitorSidePanels campaignId={campaignId} pollAggressive={isRunning} />
    </div>
  );
}
