import type { ActivityLogItem } from '../services/api';

/** Maps activity_log.action → analyticsFeature.activity.actionLabels key. */
export const ACTIVITY_ACTION_LABEL_KEYS: Record<string, string> = {
  'device.connect': 'device_connect',
  'device.disconnect': 'device_disconnect',
  'device.error': 'device_error',
  'device.dead': 'device_dead',
  'device.revived': 'device_revived',
  'device.paired': 'device_paired',
  'device.repaired': 'device_repaired',
  'device.unpaired': 'device_unpaired',
  'device.force_released': 'device_force_released',
  'device.state_reset': 'device_state_reset',
  'task.done': 'task_done',
  'task.failed': 'task_failed',
  'campaign.run': 'campaign_run',
  'campaign.complete': 'campaign_complete',
  'campaign.created': 'campaign_created',
  'campaign.updated': 'campaign_updated',
  'campaign.archived': 'campaign_archived',
  'campaign.status.changed': 'campaign_status_changed',
  'campaign.completed': 'campaign_completed',
  'campaign.failed': 'campaign_failed',
  'campaign.dispatched': 'campaign_dispatched',
  'campaign.dlq_opened': 'campaign_dlq_opened',
  'schedule.triggered': 'schedule_triggered',
  'schedule.run.terminal': 'schedule_run_terminal',
  'schedule.run_failed': 'schedule_run_failed',
  'execution.created': 'execution_created',
  'execution.started': 'execution_started',
  'execution.completed': 'execution_completed',
  'execution.failed': 'execution_failed',
  'execution.cancelled': 'execution_cancelled',
  'execution.paused': 'execution_paused',
  'execution.resumed': 'execution_resumed',
  'execution.dlq.opened': 'execution_dlq_opened',
  'execution.dlq.replayed': 'execution_dlq_replayed',
  'execution.dlq.closed': 'execution_dlq_closed',
  'scenario.created': 'scenario_created',
  'scenario.updated': 'scenario_updated',
  'scenario.archived': 'scenario_archived',
  'scenario.restored': 'scenario_restored',
  'session.claimed': 'session_claimed',
  'session.released': 'session_released',
  'session.released.execution_terminal': 'session_released_execution_terminal',
  'session.force_released': 'session_force_released',
  'session.auto_released': 'session_auto_released',
  'session.revoked': 'session_revoked',
  'step.started': 'step_started',
  'step.completed': 'step_completed',
  'step.failed': 'step_failed',
  'step.retried': 'step_retried',
  'auth.login.success': 'auth_login_success',
  'auth.login.failed': 'auth_login_failed',
  'auth.login.org_disabled': 'auth_login_org_disabled',
  'auth.logout': 'auth_logout',
  'auth.refresh': 'auth_refresh',
  'auth.refresh.replay_attempt': 'auth_refresh_replay',
  'ws.connected': 'ws_connected',
  'ws.auth.rejected': 'ws_auth_rejected',
  'admin.access': 'admin_access',
  'admin.access.denied': 'admin_access_denied',
  'account.locked': 'account_locked',
  'account.auto_unlocked': 'account_auto_unlocked',
  'account.admin_unlocked': 'account_admin_unlocked',
  'account.rotated': 'account_rotated',
  'account.lock_skipped_last_admin': 'account_lock_skipped_last_admin',
  'account.created': 'account_created',
  'account.updated': 'account_updated',
  'account.state_changed': 'account_state_changed',
  'account.status_changed': 'account_state_changed',
  'account.device_assigned': 'account_device_assigned',
  'account.device_unassigned': 'account_device_unassigned',
  'account.usage_started': 'account_usage_started',
  'account.usage_ended': 'account_usage_ended',
  'account.session.login_required': 'account_session_login_required',
  'account.session.confirmed': 'account_session_confirmed',
  'account.session.invalidated': 'account_session_invalidated',
  'account.action': 'account_action',
  'member.invited': 'member_invited',
  'member.role_changed': 'member_role_changed',
  'password.changed': 'password_changed',
  'password.policy_violation': 'password_policy_violation',
  'rate_limit.exceeded': 'rate_limit_exceeded',
  'ownership.violation': 'ownership_violation',
  'content.milestone': 'content_milestone',
  'dlq.threshold': 'dlq_threshold',
  'device.offline': 'device_offline',
  'device.online': 'device_online'
};

export const DEDICATED_ACTIVITY_TITLE_ACTIONS = new Set([
  'device.connect',
  'device.disconnect',
  'device.error',
  'task.done',
  'task.failed',
  'campaign.run',
  'campaign.complete',
  'schedule.triggered',
  'auth.login.success',
  'auth.login.failed',
  'auth.login.org_disabled',
  'auth.logout',
  'auth.refresh',
  'auth.refresh.replay_attempt',
  'ws.connected',
  'ws.auth.rejected',
  'campaign.status.changed',
  'campaign.created',
  'campaign.updated',
  'campaign.archived',
  'campaign.completed',
  'campaign.failed',
  'campaign.dispatched',
  'campaign.dlq_opened',
  'execution.cancelled',
  'execution.paused',
  'execution.resumed',
  'execution.completed',
  'execution.failed',
  'execution.dlq.opened',
  'execution.dlq.replayed',
  'execution.dlq.closed',
  'scenario.created',
  'scenario.updated',
  'scenario.archived',
  'scenario.restored',
  'session.claimed',
  'session.released',
  'session.released.execution_terminal',
  'session.force_released',
  'session.auto_released',
  'device.dead',
  'device.revived',
  'schedule.run_failed',
  'schedule.run.terminal'
]);

type ActivityTranslate = (
  key: string,
  values?: Record<string, string | number>
) => string;

function detailString(
  details: Record<string, unknown>,
  ...keys: string[]
): string {
  for (const key of keys) {
    const value = details[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function shortId(id: string): string {
  const trimmed = id.trim();
  if (trimmed.length <= 12) return trimmed;
  return `${trimmed.slice(0, 8)}…`;
}

export function formatActivityStatus(
  status: string,
  t: ActivityTranslate
): string {
  const key = `statusLabels.${status}` as const;
  try {
    const translated = t(key);
    if (translated !== key && !translated.endsWith(`.${key}`)) {
      return translated;
    }
  } catch {
    // missing key — fall through
  }
  return status.replaceAll('_', ' ');
}

export function formatActivityReleaseReason(
  reason: string,
  t: ActivityTranslate
): string {
  if (!reason) return '';
  const key = `releaseReasonLabels.${reason}` as const;
  try {
    const translated = t(key);
    if (translated !== key) return translated;
  } catch {
    // missing key
  }
  return reason.replaceAll('_', ' ');
}

export function resolveActivityActionLabel(
  action: string,
  t: ActivityTranslate
): string {
  if (action.startsWith('account.action.')) {
    const actionType = action.slice('account.action.'.length);
    const labelKey = `actionLabels.account_action_${actionType.replaceAll('.', '_')}`;
    try {
      const translated = t(labelKey);
      if (translated !== labelKey) return translated;
    } catch {
      // missing key — fall through
    }
    return t('actionLabels.account_action');
  }
  const labelKey = ACTIVITY_ACTION_LABEL_KEYS[action];
  if (labelKey) {
    return t(`actionLabels.${labelKey}`);
  }
  if (action.startsWith('user.')) {
    return t('actionLabels.user_action');
  }
  if (action.startsWith('auth.') || action.startsWith('account.')) {
    return t('categoryLabels.account');
  }
  if (action.startsWith('ws.')) {
    return t('categoryLabels.connection');
  }
  if (action.startsWith('admin.')) {
    return t('categoryLabels.admin');
  }
  if (action.startsWith('execution.')) {
    return t('categoryLabels.execution');
  }
  if (action.startsWith('campaign.')) {
    return t('categoryLabels.campaign');
  }
  if (action.startsWith('scenario.')) {
    return t('categoryLabels.scenario');
  }
  if (action.startsWith('session.')) {
    return t('categoryLabels.session');
  }
  if (action.startsWith('schedule.')) {
    return t('categoryLabels.schedule');
  }
  return action.replaceAll('.', ' · ');
}

export function resolveDedicatedActivityTitle(
  item: ActivityLogItem,
  t: ActivityTranslate
): string | null {
  const details = (item.details ?? {}) as Record<string, unknown>;
  const campaignName = detailString(details, 'campaign_name', 'name');
  const scenarioName = detailString(details, 'scenario_name', 'name');
  const fromStatus = detailString(details, 'from');
  const toStatus = detailString(details, 'to');

  switch (item.action) {
    case 'campaign.status.changed':
      if (fromStatus && toStatus) {
        return t('titles.campaignStatusChanged', {
          from: formatActivityStatus(fromStatus, t),
          to: formatActivityStatus(toStatus, t)
        });
      }
      return t('titles.campaignStatusChangedGeneric');
    case 'campaign.created':
      return campaignName
        ? t('titles.campaignCreated', { name: campaignName })
        : t('titles.campaignCreatedGeneric');
    case 'campaign.updated':
      return campaignName
        ? t('titles.campaignUpdated', { name: campaignName })
        : t('titles.campaignUpdatedGeneric');
    case 'campaign.archived':
      return campaignName
        ? t('titles.campaignArchived', { name: campaignName })
        : t('titles.campaignArchivedGeneric');
    case 'campaign.completed':
      return campaignName
        ? t('titles.campaignCompleted', { name: campaignName })
        : t('titles.campaignCompletedGeneric');
    case 'campaign.failed':
      return campaignName
        ? t('titles.campaignFailedNotify', { name: campaignName })
        : t('titles.campaignFailedGeneric');
    case 'campaign.dispatched':
      return campaignName
        ? t('titles.campaignDispatched', { name: campaignName })
        : t('titles.campaignDispatchedGeneric');
    case 'campaign.dlq_opened':
      return t('titles.campaignDlqOpened');
    case 'execution.cancelled':
      return t('titles.executionCancelled');
    case 'execution.paused':
      return t('titles.executionPaused');
    case 'execution.resumed':
      return t('titles.executionResumed');
    case 'execution.completed':
      return t('titles.executionCompleted');
    case 'execution.failed':
      return t('titles.executionFailed');
    case 'execution.dlq.opened':
      return t('titles.executionDlqOpened');
    case 'execution.dlq.replayed':
      return t('titles.executionDlqReplayed');
    case 'execution.dlq.closed':
      return t('titles.executionDlqClosed');
    case 'scenario.created':
      return scenarioName
        ? t('titles.scenarioCreated', { name: scenarioName })
        : t('titles.scenarioCreatedGeneric');
    case 'scenario.updated':
      return scenarioName
        ? t('titles.scenarioUpdated', { name: scenarioName })
        : t('titles.scenarioUpdatedGeneric');
    case 'scenario.archived':
      return scenarioName
        ? t('titles.scenarioArchived', { name: scenarioName })
        : t('titles.scenarioArchivedGeneric');
    case 'scenario.restored':
      return scenarioName
        ? t('titles.scenarioRestored', { name: scenarioName })
        : t('titles.scenarioRestoredGeneric');
    case 'session.claimed':
      return t('titles.sessionClaimed');
    case 'session.released':
      return t('titles.sessionReleased');
    case 'session.released.execution_terminal':
      return t('titles.sessionReleasedExecutionTerminal');
    case 'session.force_released':
      return t('titles.sessionForceReleased');
    case 'session.auto_released':
      return t('titles.sessionAutoReleased');
    case 'device.dead':
      return t('titles.deviceDead');
    case 'device.revived':
      return t('titles.deviceRevived');
    case 'schedule.run_failed':
      return t('titles.scheduleRunFailed');
    case 'schedule.run.terminal': {
      const status = detailString(details, 'status');
      if (status) {
        return t('titles.scheduleRunTerminal', {
          status: formatActivityStatus(status, t)
        });
      }
      return t('titles.scheduleRunTerminalGeneric');
    }
    default:
      return null;
  }
}

export function resolveDomainActivityDescription(
  item: ActivityLogItem,
  t: ActivityTranslate,
  deviceSerialLine: (serial: string) => string
): string | null {
  const details = (item.details ?? {}) as Record<string, unknown>;
  const parts: string[] = [];

  const campaignId = detailString(details, 'campaign_id');
  const campaignName = detailString(details, 'campaign_name', 'campaignName');
  const executionId = detailString(details, 'execution_id');
  const scenarioId = detailString(details, 'scenario_id');
  const scenarioName = detailString(details, 'scenario_name', 'scenarioName');
  const reason = detailString(details, 'reason');
  const releaseReason = detailString(details, 'release_reason');

  const scheduleId = detailString(details, 'schedule_id');
  const runId = detailString(details, 'run_id');
  const runStatus = detailString(details, 'status');

  if (item.action.startsWith('schedule.') && scheduleId) {
    parts.push(t('contextSchedule', { id: shortId(scheduleId) }));
  }
  if (item.action === 'schedule.run.terminal' && runId) {
    parts.push(t('contextScheduleRun', { id: shortId(runId) }));
  }
  if (item.action.startsWith('schedule.') && runStatus) {
    parts.push(formatActivityStatus(runStatus, t));
  }

  if (item.action.startsWith('campaign.') && campaignId) {
    parts.push(
      campaignName
        ? t('contextCampaignName', { name: campaignName })
        : t('contextCampaignGeneric')
    );
  }
  if (item.action.startsWith('execution.') && executionId) {
    parts.push(t('contextExecutionGeneric'));
  } else if (item.action.startsWith('execution.') && item.entity_id) {
    parts.push(t('contextExecutionGeneric'));
  }
  if (item.action.startsWith('scenario.') && scenarioId) {
    parts.push(
      scenarioName
        ? t('contextScenarioName', { name: scenarioName })
        : t('contextScenarioGeneric')
    );
  } else if (
    item.entity_type === 'org_scenario' &&
    item.entity_id &&
    item.action.startsWith('scenario.')
  ) {
    parts.push(t('contextScenarioGeneric'));
  }

  const formattedReason = formatActivityReleaseReason(reason, t);
  if (formattedReason) parts.push(formattedReason);

  const formattedRelease = formatActivityReleaseReason(releaseReason, t);
  if (formattedRelease && formattedRelease !== formattedReason) {
    parts.push(formattedRelease);
  }

  if (item.device_serial?.trim()) {
    parts.push(deviceSerialLine(item.device_serial.trim()));
  } else if (item.action.startsWith('session.')) {
    const serial =
      detailString(details, 'device_serial') || nestedPathSerial(details);
    if (serial) parts.push(deviceSerialLine(serial));
  }

  if (item.user_name?.trim()) {
    parts.push(t('performedBy', { user: item.user_name.trim() }));
  }

  return parts.length > 0 ? parts.join(' · ') : null;
}

function nestedPathSerial(details: Record<string, unknown>): string {
  const pathParams = details.path_params;
  if (!pathParams || typeof pathParams !== 'object') return '';
  const serial = (pathParams as Record<string, unknown>).serial;
  return typeof serial === 'string' ? serial.trim() : '';
}
