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
import {
  ACCOUNTS_PAGE_LIMIT,
  useAccounts
} from '@/features/accounts/hooks/use-accounts';
import type { CampaignDeviceOut } from '../types';
import type {
  CampaignAccountBindingMode,
  CampaignAccountBindingValue
} from '../lib/campaign-account-binding';

export type {
  CampaignAccountBindingMode,
  CampaignAccountBindingValue
} from '../lib/campaign-account-binding';
export {
  campaignBindingFromEntity,
  campaignBindingToPayload
} from '../lib/campaign-account-binding';

export function CampaignAccountBindingFields({
  value,
  onChange,
  platform,
  devices = [],
  showPerDevice = false,
  disabled
}: {
  value: CampaignAccountBindingValue;
  onChange: (next: CampaignAccountBindingValue) => void;
  platform?: string;
  devices?: CampaignDeviceOut[];
  showPerDevice?: boolean;
  disabled?: boolean;
}) {
  const t = useTranslations('campaignsFeature.accountBinding');
  const groupQuery = useMemo(
    () => (platform ? { platform } : undefined),
    [platform]
  );
  const { data: groups = [] } = useAccountGroups(groupQuery);
  const { data: accounts = [] } = useAccounts(
    platform
      ? { platform, limit: ACCOUNTS_PAGE_LIMIT }
      : { limit: ACCOUNTS_PAGE_LIMIT }
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
              scenarioAccountId: '',
              perDeviceAccounts: value.perDeviceAccounts
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

      {showPerDevice && (
        <div className='space-y-2 border-t pt-3'>
          <div>
            <Label className='text-xs'>{t('perDeviceLabel')}</Label>
            <p className='text-[11px] text-muted-foreground'>
              {t('perDeviceHint')}
            </p>
          </div>
          {!devices.length ? (
            <p className='text-[11px] text-muted-foreground'>
              {t('perDeviceEmpty')}
            </p>
          ) : (
            <div className='max-h-64 space-y-2 overflow-y-auto pr-1'>
              {devices.map((device) => (
                <div
                  key={device.id}
                  className='grid gap-1.5 rounded-md border p-2 sm:grid-cols-[minmax(0,1fr)_minmax(180px,1fr)] sm:items-center'
                >
                  <div className='min-w-0'>
                    <p className='truncate text-xs font-medium'>
                      {device.name || device.serial}
                    </p>
                    <p className='truncate text-[10px] text-muted-foreground'>
                      {device.serial}
                    </p>
                  </div>
                  <Select
                    value={value.perDeviceAccounts[device.id] || '_fallback'}
                    disabled={disabled}
                    onValueChange={(accountId) => {
                      const next = { ...value.perDeviceAccounts };
                      if (accountId === '_fallback') delete next[device.id];
                      else next[device.id] = accountId;
                      onChange({ ...value, perDeviceAccounts: next });
                    }}
                  >
                    <SelectTrigger className='h-8 w-full text-xs'>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className='z-[10001]'>
                      <SelectItem value='_fallback'>
                        {t('useFallback')}
                      </SelectItem>
                      {accounts.map((account) => (
                        <SelectItem key={account.id} value={account.id}>
                          {account.username}
                          {account.display_name
                            ? ` · ${account.display_name}`
                            : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
