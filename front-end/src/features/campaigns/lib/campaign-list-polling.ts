export const CAMPAIGN_ROW_ACTIVE_POLL_MS = 15_000;
export const CAMPAIGN_ROW_IDLE_STALE_MS = 60_000;
export const CAMPAIGN_ROW_ACTIVE_STALE_MS = 10_000;

const ACTIVE_CAMPAIGN_STATUSES = new Set(['running', 'paused']);
/** Never dispatched — no run stats to fetch, so the row stays a cheap "—". */
const NEVER_RUN_CAMPAIGN_STATUSES = new Set(['draft', 'scheduled']);

export function shouldPollCampaignRow(status: string): boolean {
  return ACTIVE_CAMPAIGN_STATUSES.has(status);
}

/** Finished campaigns are exactly the ones with a last run to show — fetch once,
 *  poll only while active. */
export function shouldFetchCampaignRowDetailsOnMount(status: string): boolean {
  return !NEVER_RUN_CAMPAIGN_STATUSES.has(status);
}

export function campaignRowPollInterval(status: string): number | false {
  return shouldPollCampaignRow(status) ? CAMPAIGN_ROW_ACTIVE_POLL_MS : false;
}

export function campaignRowStaleTime(status: string): number {
  return shouldPollCampaignRow(status)
    ? CAMPAIGN_ROW_ACTIVE_STALE_MS
    : CAMPAIGN_ROW_IDLE_STALE_MS;
}
