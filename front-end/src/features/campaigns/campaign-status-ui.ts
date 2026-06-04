import type { CampaignStatus } from './types';

export type CampaignStatusVariant =
  | 'secondary'
  | 'default'
  | 'outline'
  | 'destructive';

export const CAMPAIGN_STATUS_VARIANT: Record<
  CampaignStatus,
  CampaignStatusVariant
> = {
  draft: 'outline',
  scheduled: 'secondary',
  idle: 'outline',
  running: 'default',
  paused: 'outline',
  completed: 'secondary',
  cancelled: 'outline',
  failed: 'destructive',
  archived: 'secondary'
};

type StatusLabelKey =
  | 'statusDraft'
  | 'statusScheduled'
  | 'statusIdle'
  | 'statusRunning'
  | 'statusPaused'
  | 'statusCompleted'
  | 'statusCancelled'
  | 'statusFailed'
  | 'statusArchived';

const STATUS_LABEL_KEYS: Record<CampaignStatus, StatusLabelKey> = {
  draft: 'statusDraft',
  scheduled: 'statusScheduled',
  idle: 'statusIdle',
  running: 'statusRunning',
  paused: 'statusPaused',
  completed: 'statusCompleted',
  cancelled: 'statusCancelled',
  failed: 'statusFailed',
  archived: 'statusArchived'
};

export function buildCampaignStatusLabels(
  t: (key: StatusLabelKey) => string
): Record<CampaignStatus, string> {
  return (Object.keys(STATUS_LABEL_KEYS) as CampaignStatus[]).reduce(
    (acc, status) => {
      acc[status] = t(STATUS_LABEL_KEYS[status]);
      return acc;
    },
    {} as Record<CampaignStatus, string>
  );
}

export function campaignStatusLabel(
  status: string,
  labels: Record<CampaignStatus, string>
): string {
  if (status in labels) {
    return labels[status as CampaignStatus];
  }
  return status;
}

export function campaignStatusVariant(status: string): CampaignStatusVariant {
  if (status in CAMPAIGN_STATUS_VARIANT) {
    return CAMPAIGN_STATUS_VARIANT[status as CampaignStatus];
  }
  return 'outline';
}
