import { ROUTES } from '@/config/routes';
import type { ActivityLogItem } from '../services/api';

const CAMPAIGN_RUN_LOG_ACTIONS = new Set([
  'campaign.run',
  'campaign.complete',
  'campaign.completed',
  'campaign.failed',
  'campaign.dispatched',
  'campaign.dlq_opened'
]);

function detailString(details: Record<string, unknown>, key: string): string {
  const value = details[key];
  return typeof value === 'string' ? value.trim() : '';
}

function campaignIdForRunLog(
  item: ActivityLogItem,
  entityType: string,
  entityId: string | undefined
): string | null {
  const details = (item.details ?? {}) as Record<string, unknown>;
  const campaignId = detailString(details, 'campaign_id');
  if (campaignId) return campaignId;
  if (entityType === 'campaign' && entityId) return entityId;
  return null;
}

/** Resolve dashboard deep link for an activity log row (DF-T-11-015). */
export function activityLogDeepLink(item: ActivityLogItem): string | null {
  const entityType = (item.entity_type ?? '').toLowerCase();
  const entityId = item.entity_id?.trim();

  if (
    entityType === 'execution' ||
    item.action.startsWith('execution.') ||
    CAMPAIGN_RUN_LOG_ACTIONS.has(item.action)
  ) {
    const campaignId = campaignIdForRunLog(item, entityType, entityId);
    if (campaignId) {
      const executionId =
        entityType === 'execution' && entityId ? entityId : null;
      return ROUTES.CAMPAIGNS.RUN_LOG(campaignId, executionId);
    }
  }

  if (entityType === 'campaign' && entityId) {
    return ROUTES.CAMPAIGNS.DETAIL(entityId);
  }
  if (entityType === 'org_scenario' && entityId) {
    return ROUTES.ORG_SCENARIOS.DETAIL(entityId);
  }
  if (
    (entityType === 'execution' || item.action.startsWith('campaign.')) &&
    entityId
  ) {
    const campaignId =
      typeof item.details?.campaign_id === 'string'
        ? item.details.campaign_id
        : entityType === 'campaign'
          ? entityId
          : null;
    if (campaignId) return ROUTES.CAMPAIGNS.DETAIL(campaignId);
  }
  if (entityType === 'schedule' && entityId) {
    return ROUTES.SCHEDULES.ROOT;
  }
  if (entityType === 'schedule_run') {
    const scheduleId =
      typeof item.details?.schedule_id === 'string'
        ? item.details.schedule_id.trim()
        : '';
    if (scheduleId) {
      return `${ROUTES.SCHEDULES.ROOT}?schedule_id=${encodeURIComponent(scheduleId)}`;
    }
    return ROUTES.SCHEDULES.ROOT;
  }
  if (entityType === 'content' && entityId) {
    return ROUTES.CONTENT.DETAIL(entityId);
  }
  if (item.device_serial?.trim()) {
    return ROUTES.DEVICES.DETAIL(item.device_serial.trim());
  }
  if (item.action.startsWith('campaign.') && entityId) {
    return ROUTES.CAMPAIGNS.DETAIL(entityId);
  }
  return null;
}
