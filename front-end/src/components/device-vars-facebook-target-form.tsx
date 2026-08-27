'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Check,
  Flag,
  Inbox,
  Loader2,
  Search,
  UserRound,
  Users
} from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { cn } from '@/lib/utils';

import {
  applyDeviceTargetFormState,
  readDeviceTargetFormState,
  type DeviceVarsTargetSnapshot,
  type DeviceVarsTargetType
} from './device-vars-target-form-model';
import { externalEntitiesApi } from '@/features/external-entities/services/api';
import type { ExternalEntityCatalogItem } from '@/features/external-entities/services/api';

type DeviceVarsFacebookTargetFormProps = {
  vars: Record<string, unknown>;
  disabled?: boolean;
  size?: 'default' | 'large';
  onChange: (vars: Record<string, unknown>) => void;
};

const TARGET_TYPES: DeviceVarsTargetType[] = ['group', 'page', 'profile'];

function toSnapshot(
  entity: ExternalEntityCatalogItem
): DeviceVarsTargetSnapshot {
  return {
    id: entity.id,
    display_name: entity.display_name,
    entity_type: entity.entity_type as DeviceVarsTargetType,
    platform: entity.platform,
    external_id: entity.external_id ?? null,
    canonical_url: entity.canonical_url ?? null
  };
}

function locatorLabel(target: DeviceVarsTargetSnapshot, fallback: string) {
  return target.canonical_url || target.external_id || fallback;
}

export function DeviceVarsFacebookTargetForm({
  vars,
  disabled = false,
  size = 'default',
  onChange
}: DeviceVarsFacebookTargetFormProps) {
  const t = useTranslations('components.deviceVarsJson.targetForm');
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? '';
  const [targetType, setTargetType] = useState<DeviceVarsTargetType>('group');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const formState = useMemo(() => readDeviceTargetFormState(vars), [vars]);
  const selectedForType = formState.selected[targetType];
  const selectedIds = useMemo(
    () => new Set(selectedForType.map((target) => target.id)),
    [selectedForType]
  );

  const catalogQuery = useQuery({
    queryKey: [
      'device-vars-target-catalog',
      orgId,
      'facebook',
      targetType,
      debouncedSearch
    ],
    queryFn: ({ signal }) =>
      externalEntitiesApi.list(
        {
          platform: 'facebook',
          entity_type: targetType,
          limit: 100,
          ...(debouncedSearch.trim() ? { search: debouncedSearch.trim() } : {})
        },
        orgId,
        signal
      ),
    enabled: Boolean(orgId)
  });

  const catalogTargets = useMemo(
    () =>
      (catalogQuery.data?.items ?? [])
        .filter((item) => item.entity_type === targetType)
        .map(toSnapshot),
    [catalogQuery.data?.items, targetType]
  );

  const rows = useMemo(() => {
    const seen = new Set<string>();
    return [...selectedForType, ...catalogTargets].filter((target) => {
      if (seen.has(target.id)) return false;
      seen.add(target.id);
      return true;
    });
  }, [catalogTargets, selectedForType]);

  const allSelectedCount = TARGET_TYPES.reduce(
    (total, type) => total + formState.selected[type].length,
    0
  );
  const listHeightClass = size === 'large' ? 'h-[360px] xl:h-[420px]' : 'h-80';

  function updateSelection(
    type: DeviceVarsTargetType,
    nextTargets: DeviceVarsTargetSnapshot[]
  ) {
    const nextState = {
      platform: 'facebook' as const,
      selected: {
        ...formState.selected,
        [type]: nextTargets
      }
    };
    onChange(applyDeviceTargetFormState(vars, nextState));
  }

  function toggleTarget(target: DeviceVarsTargetSnapshot, checked: boolean) {
    const current = formState.selected[target.entity_type];
    const next = checked
      ? current.some((item) => item.id === target.id)
        ? current
        : [...current, target]
      : current.filter((item) => item.id !== target.id);
    updateSelection(target.entity_type, next);
  }

  return (
    <div className='flex min-h-0 min-w-0 max-w-full flex-col gap-3 overflow-hidden'>
      <Tabs
        value={targetType}
        onValueChange={(value) => {
          setTargetType(value as DeviceVarsTargetType);
          setSearch('');
        }}
      >
        <TabsList className='grid h-8 w-full min-w-0 grid-cols-3'>
          <TabsTrigger value='group' className='min-w-0 gap-1 text-xs'>
            <Users className='size-3.5' />
            <span className='truncate'>{t('types.group')}</span>
          </TabsTrigger>
          <TabsTrigger value='page' className='min-w-0 gap-1 text-xs'>
            <Flag className='size-3.5' />
            <span className='truncate'>{t('types.page')}</span>
          </TabsTrigger>
          <TabsTrigger value='profile' className='min-w-0 gap-1 text-xs'>
            <UserRound className='size-3.5' />
            <span className='truncate'>{t('types.profile')}</span>
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className='grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center'>
        <div className='relative min-w-0'>
          <Search className='absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('searchPlaceholder')}
            aria-label={t('searchPlaceholder')}
            className='h-9 pl-9 text-sm'
            disabled={disabled}
          />
        </div>
        <div className='flex min-w-0 flex-wrap items-center gap-1.5 overflow-hidden'>
          <Badge variant='secondary' className='max-w-full rounded'>
            {t('selectedTotal', { count: allSelectedCount })}
          </Badge>
          {TARGET_TYPES.map((type) => (
            <Badge
              key={type}
              variant='outline'
              className='min-w-0 rounded font-normal'
            >
              <span className='truncate'>
                {t(`types.${type}`)} {formState.selected[type].length}
              </span>
            </Badge>
          ))}
        </div>
      </div>

      <ScrollArea
        className={cn(
          'min-w-0 max-w-full overflow-hidden rounded-md border bg-background',
          listHeightClass
        )}
      >
        <div className='min-w-0 max-w-full' aria-busy={catalogQuery.isLoading}>
          {catalogQuery.isLoading ? (
            Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className='flex h-14 min-w-0 items-center gap-3 border-b px-3'
              >
                <Skeleton className='size-4 rounded' />
                <div className='min-w-0 flex-1 space-y-2'>
                  <Skeleton className='h-3 w-2/3' />
                  <Skeleton className='h-2.5 w-1/3' />
                </div>
              </div>
            ))
          ) : catalogQuery.isError ? (
            <div role='alert' className='p-4 text-sm text-destructive'>
              {t('loadError')}
            </div>
          ) : rows.length === 0 ? (
            <div
              className={cn(
                'grid place-items-center px-4 text-center',
                listHeightClass
              )}
            >
              <div>
                <Inbox className='mx-auto mb-2 size-7 text-muted-foreground' />
                <p className='text-sm font-medium'>{t('emptyTitle')}</p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  {t('emptyDescription')}
                </p>
              </div>
            </div>
          ) : (
            rows.map((target) => {
              const selected = selectedIds.has(target.id);
              return (
                <label
                  key={`${target.entity_type}:${target.id}`}
                  className={cn(
                    'flex min-h-14 min-w-0 cursor-pointer items-center gap-3 border-b px-3 py-2.5 transition-colors last:border-b-0 focus-within:bg-muted/50 hover:bg-muted/50',
                    selected && 'bg-primary/[0.04]',
                    disabled && 'cursor-not-allowed opacity-70'
                  )}
                >
                  <Checkbox
                    checked={selected}
                    disabled={disabled}
                    className='shrink-0'
                    onCheckedChange={(checked) =>
                      toggleTarget(target, checked === true)
                    }
                    aria-label={t('toggleTarget', {
                      name: target.display_name
                    })}
                  />
                  <span className='min-w-0 flex-1 overflow-hidden'>
                    <span
                      className='block truncate text-sm font-medium'
                      title={target.display_name}
                    >
                      {target.display_name}
                    </span>
                    <span
                      className='block truncate text-xs text-muted-foreground'
                      title={locatorLabel(target, t('noLocator'))}
                    >
                      {locatorLabel(target, t('noLocator'))}
                    </span>
                  </span>
                  {selected ? (
                    <Check className='size-4 shrink-0 text-primary' />
                  ) : null}
                </label>
              );
            })
          )}
        </div>
      </ScrollArea>

      {catalogQuery.isFetching && !catalogQuery.isLoading ? (
        <div className='flex items-center gap-1.5 text-[11px] text-muted-foreground'>
          <Loader2 className='size-3 animate-spin' />
          {t('refreshing')}
        </div>
      ) : null}
    </div>
  );
}
