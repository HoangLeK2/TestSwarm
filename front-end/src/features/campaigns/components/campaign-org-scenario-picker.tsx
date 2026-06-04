'use client';

import { useMemo } from 'react';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { CreateOrgScenarioDialog } from '@/features/org-scenarios/components/create-scenario-dialog';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import {
  canSelectOrgScenarioForCampaign,
  isOrgScenarioVisibleInCampaignPicker
} from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import type { OrgScenarioSummaryOut } from '@/features/org-scenarios/services/api';

export function CampaignOrgScenarioPicker({
  selectedIds,
  onSelectedIdsChange,
  disabled = false,
  messagesNs = 'createDialog'
}: {
  selectedIds: string[];
  onSelectedIdsChange: (ids: string[]) => void;
  disabled?: boolean;
  messagesNs?: 'createDialog' | 'entityDialog';
}) {
  const t = useTranslations(`campaignsFeature.${messagesNs}`);
  const { data: orgScenarios } = useOrgScenarios();

  const selectableScenarios = useMemo(
    () =>
      (orgScenarios ?? []).filter((scenario) =>
        isOrgScenarioVisibleInCampaignPicker(scenario)
      ),
    [orgScenarios]
  );

  const onScenarioCreated = (created: OrgScenarioSummaryOut) => {
    onSelectedIdsChange(Array.from(new Set([...selectedIds, created.id])));
    toast.success(t('createScenarioSuccess'));
  };

  const toggleScenario = (scenarioId: string, checked: boolean) => {
    onSelectedIdsChange(
      checked
        ? Array.from(new Set([...selectedIds, scenarioId]))
        : selectedIds.filter((id) => id !== scenarioId)
    );
  };

  return (
    <div className='space-y-2'>
      <div className='flex items-center justify-end'>
        <CreateOrgScenarioDialog
          onCreated={onScenarioCreated}
          trigger={
            <Button
              type='button'
              variant='outline'
              size='sm'
              className='h-8 gap-1'
              disabled={disabled}
            >
              <Plus size={14} />
              {t('createScenario')}
            </Button>
          }
        />
      </div>
      <div
        className={cn(
          'max-h-52 space-y-2 overflow-y-auto rounded-md border p-3',
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
        {selectableScenarios.map((scenario) => {
          const selectable = canSelectOrgScenarioForCampaign(scenario);
          return (
            <label
              key={scenario.id}
              className={cn(
                'flex items-start gap-2 text-sm',
                selectable ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'
              )}
            >
              <Checkbox
                checked={selectedIds.includes(scenario.id)}
                disabled={!selectable}
                onCheckedChange={(checked) =>
                  toggleScenario(scenario.id, checked === true)
                }
              />
              <span>
                <span className='font-medium'>{scenario.name}</span>
                <span className='block text-xs text-muted-foreground'>
                  {scenario.kind} · v{scenario.scenario_version}
                  {!selectable ? ` · ${t('scenarioNotRunnable')}` : ''}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
