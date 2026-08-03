'use client';

import { FileText, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { useCampaign, useScenarios } from '../../hooks/use-campaigns';
import { isCampaignEntityOut } from '../../services/api';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { ScenarioListDialog } from '../scenario-list-dialog';
import type { CampaignOut } from '../../types';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { cn } from '@/lib/utils';

export function CampaignScenarioSummary({
  campaign,
  triggerClassName
}: {
  campaign: CampaignOut;
  triggerClassName?: string;
}) {
  const t = useTranslations('campaignsFeature.scenarioList');
  const { canUpdate } = useResourcePermissions('campaigns');
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: fetchedScenarios } = useScenarios(campaign.id, dialogOpen);
  const scenarios = fetchedScenarios ?? campaign.scenarios ?? [];
  const { data: detail } = useCampaign(
    campaign.id,
    dialogOpen && !campaign.scenario_refs?.length
  );
  const { data: orgScenarios = [] } = useOrgScenarios({
    enabled: dialogOpen
  });
  const entityRefs =
    campaign.scenario_refs ??
    (detail && isCampaignEntityOut(detail) ? detail.scenario_refs : []) ??
    [];
  const entityRefCount = entityRefs.length;
  const entityRefNames = entityRefs
    .map(
      (ref) =>
        orgScenarios.find((row) => row.id === ref.scenario_id)?.name ?? ''
    )
    .filter(Boolean);
  const totalSteps = scenarios.reduce((s, sc) => s + sc.steps.length, 0);
  const hasScenario = totalSteps > 0 || entityRefCount > 0;

  const label = hasScenario
    ? entityRefNames.length > 0
      ? t('summaryEntityRefNames', { names: entityRefNames.join(', ') })
      : entityRefCount > 0 && totalSteps === 0
        ? t('summaryEntityRefs', { count: entityRefCount })
        : t('summaryCount', { scenarios: scenarios.length, steps: totalSteps })
    : t('summaryEmpty');

  const buttonClassName = cn(
    'h-7 max-w-[190px] justify-start gap-1.5 px-2 text-[11px]',
    triggerClassName
  );

  if (!canUpdate && !hasScenario) {
    return (
      <Button
        type='button'
        variant='outline'
        size='sm'
        className={buttonClassName}
        disabled
        title={t('emptyDescription')}
      >
        <FileText size={12} className='shrink-0 text-muted-foreground' />
        <span className='truncate'>{label}</span>
      </Button>
    );
  }

  return (
    <ScenarioListDialog
      campaign={campaign}
      open={dialogOpen}
      onOpenChange={setDialogOpen}
    >
      <Button
        type='button'
        variant='outline'
        size='sm'
        className={cn(
          buttonClassName,
          !hasScenario &&
            'border-primary/40 text-primary hover:border-primary/50 hover:bg-primary/[0.06]'
        )}
        title={hasScenario ? t('summaryTitle') : t('emptyDescription')}
      >
        <FileText size={12} className='shrink-0 text-muted-foreground' />
        <span
          className={cn(
            'min-w-0 flex-1 truncate',
            hasScenario ? 'font-medium text-foreground' : 'font-medium'
          )}
        >
          {label}
        </span>
        {hasScenario ? (
          <ChevronRight size={12} className='shrink-0 text-muted-foreground' />
        ) : null}
      </Button>
    </ScenarioListDialog>
  );
}
