export const CAMPAIGN_ROW_ACTIVE_POLL_MS = 15_000;
export const CAMPAIGN_ROW_IDLE_STALE_MS = 60_000;
export const CAMPAIGN_ROW_ACTIVE_STALE_MS = 10_000;

const ACTIVE_CAMPAIGN_STATUSES = new Set(['running', 'paused']);

export function shouldPollCampaignRow(status: string): boolean {
  return ACTIVE_CAMPAIGN_STATUSES.has(status);
}

export function campaignRowPollInterval(status: string): number | false {
  return shouldPollCampaignRow(status) ? CAMPAIGN_ROW_ACTIVE_POLL_MS : false;
}

export function campaignRowStaleTime(status: string): number {
  return shouldPollCampaignRow(status)
    ? CAMPAIGN_ROW_ACTIVE_STALE_MS
    : CAMPAIGN_ROW_IDLE_STALE_MS;
}
