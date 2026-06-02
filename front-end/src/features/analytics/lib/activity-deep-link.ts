import { ROUTES } from '@/config/routes';
import type { ActivityLogItem } from '../services/api';

/** Resolve dashboard deep link for an activity log row (DF-T-11-015). */
export function activityLogDeepLink(item: ActivityLogItem): string | null {
  const entityType = (item.entity_type ?? '').toLowerCase();
  const entityId = item.entity_id?.trim();

  if (entityType === 'campaign' && entityId) {
    return ROUTES.CAMPAIGNS.DETAIL(entityId);
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
