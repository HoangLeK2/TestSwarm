'use client';

import { useEffect, useMemo } from 'react';

import { ROUTES } from '@/config/routes';
import { useAccounts } from '@/features/accounts/hooks/use-accounts';
import { normalizeAccountState } from '@/features/accounts/lib/account-fsm';
import { useUser } from '@/features/auth';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';
import type { CampaignOut } from '@/features/campaigns/types';
import { useDevices } from '@/features/devices/hooks/use-devices';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { useSchedules } from '@/features/schedules/hooks/use-schedules';
import { useRouter } from '@/i18n/navigation';

import { buildWorkspaceJourney } from '../lib/workspace-journey';

function campaignHasScenario(campaign: CampaignOut): boolean {
  return Boolean(
    campaign.scenario_refs?.length ||
      campaign.scenarios?.length ||
      campaign.scenario
  );
}

function campaignHasTarget(campaign: CampaignOut): boolean {
  return Boolean(campaign.devices?.length || campaign.target_group_id);
}

const RAN_STATUSES = new Set([
  'running',
  'paused',
  'completed',
  'cancelled',
  'failed'
]);

export function WorkspaceJourneyRedirect() {
  const router = useRouter();
  const { user } = useUser();
  const devices = useDevices();
  const accounts = useAccounts({ limit: 200 });
  const scenarios = useOrgScenarios();
  const campaigns = useCampaigns();
  const schedules = useSchedules();

  const isLoading =
    devices.isLoading ||
    accounts.isLoading ||
    scenarios.isLoading ||
    campaigns.isLoading ||
    schedules.isLoading;

  const target = useMemo(() => {
    const accountRows = accounts.data ?? [];
    const campaignRows = campaigns.data ?? [];
    const signals = {
      deviceCount: devices.data?.length ?? 0,
      linkedAccountCount: accountRows.filter((account) =>
        ['assigned', 'active'].includes(
          normalizeAccountState(account.state || account.status)
        )
      ).length,
      runnableScenarioCount: (scenarios.data ?? []).filter(
        (scenario) =>
          scenario.status !== 'archived' && Boolean(scenario.is_runnable)
      ).length,
      readyCampaignCount: campaignRows.filter(
        (campaign) =>
          campaignHasScenario(campaign) && campaignHasTarget(campaign)
      ).length,
      campaignRunCount: campaignRows.filter((campaign) =>
        RAN_STATUSES.has(campaign.status)
      ).length,
      activeScheduleCount: (schedules.data ?? []).filter(
        (schedule) => schedule.is_enabled
      ).length
    };
    const current = buildWorkspaceJourney(signals).find(
      (step) => step.state === 'current'
    );

    if (current?.key === 'devices') {
      const canAllocatePhones =
        user?.role === 'superadmin' || user?.orgRole === 'admin';
      return canAllocatePhones ? ROUTES.ADMIN.AGENTS : ROUTES.DEVICES.ROOT;
    }
    if (current?.key === 'accounts') return ROUTES.ACCOUNTS.ROOT;
    if (current?.key === 'scenarios') return ROUTES.ORG_SCENARIOS.ROOT;
    if (current?.key === 'campaigns') return ROUTES.CAMPAIGNS.ROOT;
    if (current?.key === 'automation') {
      return signals.campaignRunCount > 0
        ? ROUTES.SCHEDULES.ROOT
        : ROUTES.CAMPAIGNS.ROOT;
    }
    return ROUTES.CAMPAIGNS.ROOT;
  }, [
    accounts.data,
    campaigns.data,
    devices.data,
    scenarios.data,
    schedules.data,
    user?.orgRole,
    user?.role
  ]);

  useEffect(() => {
    if (!isLoading) router.replace(target);
  }, [isLoading, router, target]);

  return null;
}
