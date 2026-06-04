'use client';

import { useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { useAccountGroups } from '@/features/account-groups/hooks/use-account-groups';
import { useAccounts } from '@/features/accounts/hooks/use-accounts';

export type CampaignAccountBindingMode = 'none' | 'group' | 'single';

export type CampaignAccountBindingValue = {
  mode: CampaignAccountBindingMode;
  accountGroupId: string;
  scenarioAccountId: string;
};

export function campaignBindingFromEntity(entity: {
  account_group_id?: string | null;
  scenario_account_id?: string | null;
}): CampaignAccountBindingValue {
  if (entity.account_group_id) {
    return {
      mode: 'group',
      accountGroupId: entity.account_group_id,
      scenarioAccountId: ''
    };
  }
  if (entity.scenario_account_id) {
    return {
      mode: 'single',
      accountGroupId: '',
      scenarioAccountId: entity.scenario_account_id
    };
  }
  return { mode: 'none', accountGroupId: '', scenarioAccountId: '' };
}

export function campaignBindingToPayload(value: CampaignAccountBindingValue): {
  account_group_id?: string;
  scenario_account_id?: string;
} {
  if (value.mode === 'group' && value.accountGroupId) {
    return { account_group_id: value.accountGroupId };
  }
  if (value.mode === 'single' && value.scenarioAccountId) {
    return { scenario_account_id: value.scenarioAccountId };
  }
  return {};
}

export function CampaignAccountBindingFields({
  value,
  onChange,
  platform,
  disabled
}: {
  value: CampaignAccountBindingValue;
  onChange: (next: CampaignAccountBindingValue) => void;
  platform?: string;
  disabled?: boolean;
}) {
  const t = useTranslations('campaignsFeature.accountBinding');
  const groupQuery = useMemo(
    () => (platform ? { platform } : undefined),
    [platform]
  );
  const { data: groups = [] } = useAccountGroups(groupQuery);
  const { data: accounts = [] } = useAccounts(
    platform ? { platform, limit: 200 } : { limit: 200 }
  );

  const pickedGroup = groups.find((g) => g.id === value.accountGroupId);

  return (
    <div className='space-y-3'>
      <div className='space-y-1.5'>
        <Label className='text-xs'>{t('modeLabel')}</Label>
        <Select
          value={value.mode}
          disabled={disabled}
          onValueChange={(mode) =>
            onChange({
              mode: mode as CampaignAccountBindingMode,
              accountGroupId: '',
              scenarioAccountId: ''
            })
          }
        >
          <SelectTrigger className='h-9 w-full'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent className='z-[10001]'>
            <SelectItem value='none'>{t('modeNone')}</SelectItem>
            <SelectItem value='group'>{t('modeGroup')}</SelectItem>
            <SelectItem value='single'>{t('modeSingle')}</SelectItem>
          </SelectContent>
        </Select>
        <p className='text-[11px] text-muted-foreground'>{t('explicitHint')}</p>
      </div>

      {value.mode === 'group' && (
        <div className='space-y-1.5'>
          <Label className='text-xs'>{t('groupLabel')}</Label>
          <Select
            value={value.accountGroupId || '_none'}
            disabled={disabled}
            onValueChange={(v) =>
              onChange({
                ...value,
                accountGroupId: v === '_none' ? '' : v
              })
            }
          >
            <SelectTrigger className='h-9 w-full'>
              <SelectValue placeholder={t('groupPlaceholder')} />
            </SelectTrigger>
            <SelectContent className='z-[10001]'>
              <SelectItem value='_none'>{t('groupNone')}</SelectItem>
              {groups.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name} ({g.member_count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {pickedGroup && (
            <p className='text-[11px] text-muted-foreground'>
              {t('groupCaption', {
                count: pickedGroup.member_count,
                strategy: pickedGroup.rotation_strategy
              })}
            </p>
          )}
          {!groups.length && (
            <p className='text-[11px] text-muted-foreground'>
              {t('groupEmpty')}
            </p>
          )}
        </div>
      )}

      {value.mode === 'single' && (
        <div className='space-y-1.5'>
          <Label className='text-xs'>{t('singleLabel')}</Label>
          <Select
            value={value.scenarioAccountId || '_none'}
            disabled={disabled}
            onValueChange={(v) =>
              onChange({
                ...value,
                scenarioAccountId: v === '_none' ? '' : v
              })
            }
          >
            <SelectTrigger className='h-9 w-full'>
              <SelectValue placeholder={t('singlePlaceholder')} />
            </SelectTrigger>
            <SelectContent className='z-[10001]'>
              <SelectItem value='_none'>{t('singleNone')}</SelectItem>
              {accounts.map((acc) => (
                <SelectItem key={acc.id} value={acc.id}>
                  {acc.username}
                  {acc.display_name ? ` · ${acc.display_name}` : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!accounts.length && (
            <p className='text-[11px] text-muted-foreground'>
              {t('singleEmpty')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
