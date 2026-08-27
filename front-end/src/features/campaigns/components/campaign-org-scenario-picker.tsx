'use client';

import { useMemo, useState } from 'react';
import { Plus, Search, X } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { CreateOrgScenarioDialog } from '@/features/org-scenarios/components/create-scenario-dialog';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import {
  canSelectOrgScenarioForCampaign,
  isOrgScenarioVisibleInCampaignPicker
} from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import type { OrgScenarioSummaryOut } from '@/features/org-scenarios/services/api';
import type { CampaignScenarioRefIn } from '../types';
import {
  CAMPAIGN_SCENARIO_REPEAT_MAX,
  CAMPAIGN_SCENARIO_REPEAT_MIN,
  normalizeCampaignScenarioRefs,
  normalizeCampaignScenarioRepeatCount
} from '../types';

type ScenarioFilter = 'all' | 'regular' | 'recovery';

function isRecoveryScenario(scenario: OrgScenarioSummaryOut): boolean {
  return (
    scenario.is_recovery_scenario === true ||
    (scenario.recovery_usage_count ?? 0) > 0
  );
}

export function CampaignOrgScenarioPicker({
  selectedIds,
  onSelectedIdsChange,
  selectedRefs,
  onSelectedRefsChange,
  disabled = false,
  messagesNs = 'createDialog',
  scenarioFilter = 'all',
  showRepeatConfig = false
}: {
  selectedIds?: string[];
  onSelectedIdsChange?: (ids: string[]) => void;
  selectedRefs?: CampaignScenarioRefIn[];
  onSelectedRefsChange?: (refs: CampaignScenarioRefIn[]) => void;
  disabled?: boolean;
  messagesNs?: 'createDialog' | 'entityDialog';
  scenarioFilter?: ScenarioFilter;
  showRepeatConfig?: boolean;
}) {
  const t = useTranslations(`campaignsFeature.${messagesNs}`);
  const { data: orgScenarios } = useOrgScenarios();
  const [searchQuery, setSearchQuery] = useState('');
  const effectiveRefs = useMemo(
    () =>
      normalizeCampaignScenarioRefs(
        selectedRefs ??
          (selectedIds ?? []).map((scenario_id) => ({
            scenario_id,
            repeat_count: CAMPAIGN_SCENARIO_REPEAT_MIN
          }))
      ),
    [selectedIds, selectedRefs]
  );
  const selectedRefById = useMemo(
    () => new Map(effectiveRefs.map((ref) => [ref.scenario_id, ref])),
    [effectiveRefs]
  );
  const selectableScenarios = useMemo(
    () =>
      (orgScenarios ?? [])
        .filter((scenario) => isOrgScenarioVisibleInCampaignPicker(scenario))
        .filter((scenario) => {
          const recovery = isRecoveryScenario(scenario);
          if (scenarioFilter === 'regular') return !recovery;
          if (scenarioFilter === 'recovery') return recovery;
          return true;
        }),
    [orgScenarios, scenarioFilter]
  );
  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const visibleScenarios = useMemo(() => {
    if (!normalizedSearchQuery) return selectableScenarios;

    return selectableScenarios.filter((scenario) => {
      const scenarioType = isRecoveryScenario(scenario)
        ? t('recoveryScenarioBadgeShort')
        : t('runScenarioBadgeShort');
      const haystack = [
        scenario.name,
        scenario.description,
        scenario.kind,
        String(scenario.scenario_version),
        scenarioType,
        ...(scenario.tags ?? [])
      ]
        .join(' ')
        .toLowerCase();

      return haystack.includes(normalizedSearchQuery);
    });
  }, [normalizedSearchQuery, selectableScenarios, t]);

  const emitSelection = (refs: CampaignScenarioRefIn[]) => {
    const normalized = normalizeCampaignScenarioRefs(refs);
    onSelectedRefsChange?.(normalized);
    onSelectedIdsChange?.(normalized.map((ref) => ref.scenario_id));
  };

  const onScenarioCreated = (created: OrgScenarioSummaryOut) => {
    if (selectedRefById.has(created.id)) return;
    emitSelection([
      ...effectiveRefs,
      { scenario_id: created.id, repeat_count: CAMPAIGN_SCENARIO_REPEAT_MIN }
    ]);
    toast.success(t('createScenarioSuccess'));
  };

  const toggleScenario = (scenarioId: string, checked: boolean) => {
    if (checked) {
      if (selectedRefById.has(scenarioId)) return;
      emitSelection([
        ...effectiveRefs,
        { scenario_id: scenarioId, repeat_count: CAMPAIGN_SCENARIO_REPEAT_MIN }
      ]);
      return;
    }
    emitSelection(
      effectiveRefs.filter((ref) => ref.scenario_id !== scenarioId)
    );
  };

  const updateRepeatCount = (scenarioId: string, value: unknown) => {
    const repeat_count = normalizeCampaignScenarioRepeatCount(value);
    emitSelection(
      effectiveRefs.map((ref) =>
        ref.scenario_id === scenarioId ? { ...ref, repeat_count } : ref
      )
    );
  };

  return (
    <div className='space-y-2'>
      <div className='flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'>
        <div className='relative min-w-0 flex-1'>
          <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t('scenarioSearchPlaceholder')}
            aria-label={t('scenarioSearchAria')}
            className='h-8 pl-8 pr-8 text-xs'
            disabled={disabled}
          />
          {searchQuery ? (
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='absolute right-1 top-1/2 size-6 -translate-y-1/2 text-muted-foreground'
              onClick={() => setSearchQuery('')}
              aria-label={t('scenarioSearchClear')}
              disabled={disabled}
            >
              <X className='size-3.5' />
            </Button>
          ) : null}
        </div>
        <CreateOrgScenarioDialog
          onCreated={onScenarioCreated}
          trigger={
            <Button
              type='button'
              variant='outline'
              size='sm'
              className='h-8 max-w-full gap-1'
              disabled={disabled}
            >
              <Plus className='size-3.5 shrink-0' />
              <span className='truncate'>{t('createScenario')}</span>
            </Button>
          }
        />
      </div>
      <div
        className={cn(
          'max-h-52 space-y-2 overflow-y-auto overflow-x-hidden rounded-md border p-3',
          disabled && 'pointer-events-none opacity-60'
        )}
      >
        {!selectableScenarios.length && (
          <p className='text-xs text-muted-foreground'>
            {messagesNs === 'entityDialog'
              ? t('noScenarios')
              : t('libraryScenariosEmpty')}
          </p>
        )}
        {selectableScenarios.length > 0 && !visibleScenarios.length ? (
          <p className='text-xs text-muted-foreground'>
            {t('scenarioSearchNoResults')}
          </p>
        ) : null}
        {visibleScenarios.map((scenario) => {
          const selectable = canSelectOrgScenarioForCampaign(scenario);
          const recovery = isRecoveryScenario(scenario);
          const selectedRef = selectedRefById.get(scenario.id);
          const checked = selectedRef != null;
          const repeatCount = normalizeCampaignScenarioRepeatCount(
            selectedRef?.repeat_count
          );
          return (
            <div
              key={scenario.id}
              className={cn(
                'grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 text-sm',
                selectable ? '' : 'cursor-not-allowed opacity-70'
              )}
            >
              <label className='flex min-w-0 flex-1 cursor-pointer items-start gap-2'>
                <Checkbox
                  checked={checked}
                  disabled={!selectable}
                  onCheckedChange={(nextChecked) =>
                    toggleScenario(scenario.id, nextChecked === true)
                  }
                />
                <span className='min-w-0 flex-1'>
                  <span className='flex min-w-0 items-center gap-2'>
                    <span className='truncate font-medium'>
                      {scenario.name}
                    </span>
                    <Badge
                      variant={recovery ? 'secondary' : 'outline'}
                      className='shrink-0 text-[10px]'
                    >
                      {recovery
                        ? t('recoveryScenarioBadgeShort')
                        : t('runScenarioBadgeShort')}
                    </Badge>
                  </span>
                  <span className='block text-xs text-muted-foreground'>
                    {scenario.kind} · v{scenario.scenario_version}
                    {!selectable ? ` · ${t('scenarioNotRunnable')}` : ''}
                  </span>
                </span>
              </label>
              {showRepeatConfig ? (
                <span className='grid w-[4.75rem] grid-cols-1 gap-1 justify-self-end'>
                  <span className='truncate text-[11px] leading-none text-muted-foreground'>
                    {t('repeatCountLabel')}
                  </span>
                  <Input
                    type='number'
                    inputMode='numeric'
                    min={CAMPAIGN_SCENARIO_REPEAT_MIN}
                    max={CAMPAIGN_SCENARIO_REPEAT_MAX}
                    value={repeatCount}
                    disabled={!selectable || !checked}
                    aria-label={t('repeatCountAria', { name: scenario.name })}
                    title={t('repeatCountAria', { name: scenario.name })}
                    onChange={(event) =>
                      updateRepeatCount(scenario.id, event.target.value)
                    }
                    className='h-7 w-full px-2 text-xs tabular-nums'
                  />
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
