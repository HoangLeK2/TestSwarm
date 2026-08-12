export type CampaignAccountBindingMode = 'none' | 'group' | 'single';

export type CampaignAccountBindingValue = {
  mode: CampaignAccountBindingMode;
  accountGroupId: string;
  scenarioAccountId: string;
  perDeviceAccounts: Record<string, string>;
};

export function campaignBindingFromEntity(entity: {
  account_group_id?: string | null;
  scenario_account_id?: string | null;
  per_device_accounts?: Record<string, string> | null;
}): CampaignAccountBindingValue {
  const perDeviceAccounts = entity.per_device_accounts ?? {};
  if (entity.account_group_id) {
    return {
      mode: 'group',
      accountGroupId: entity.account_group_id,
      scenarioAccountId: '',
      perDeviceAccounts
    };
  }
  if (entity.scenario_account_id) {
    return {
      mode: 'single',
      accountGroupId: '',
      scenarioAccountId: entity.scenario_account_id,
      perDeviceAccounts
    };
  }
  return {
    mode: 'none',
    accountGroupId: '',
    scenarioAccountId: '',
    perDeviceAccounts
  };
}

export function campaignBindingToPayload(value: CampaignAccountBindingValue): {
  account_group_id?: string;
  scenario_account_id?: string;
  per_device_accounts?: Record<string, string>;
} {
  const per_device_accounts = Object.fromEntries(
    Object.entries(value.perDeviceAccounts).filter(([, accountId]) => accountId)
  );
  if (value.mode === 'group' && value.accountGroupId) {
    return { account_group_id: value.accountGroupId, per_device_accounts };
  }
  if (value.mode === 'single' && value.scenarioAccountId) {
    return {
      scenario_account_id: value.scenarioAccountId,
      per_device_accounts
    };
  }
  return { per_device_accounts };
}
