'use client';

import { ChevronRight, FileText, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { ScenarioDialog } from '../scenario-dialog';
import type { CampaignOut, ScenarioOut } from '../../types';
import { useDeleteScenario } from '../../hooks/use-campaigns';

export function ScenarioRow({
  campaign,
  scenario,
  onDeleted
}: {
  campaign: CampaignOut;
  scenario: ScenarioOut;
  onDeleted: () => void;
}) {
  const t = useTranslations('campaignsFeature.scenarioList');
  const { mutate: deleteScenario, isPending } = useDeleteScenario();

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(t('deleteConfirm', { name: scenario.name }))) return;

    deleteScenario(
      { campaignId: campaign.id, scenarioId: scenario.id },
      {
        onSuccess: () => {
          toast.success(t('deleteSuccess'));
          onDeleted();
        },
        onError: () => toast.error(t('deleteFailed'))
      }
    );
  };

  return (
    <div className='flex items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted/40'>
      <FileText size={14} className='shrink-0 text-muted-foreground' />
      <div className='min-w-0 flex-1'>
        <div className='truncate font-medium'>{scenario.name}</div>
        {scenario.instructions && <div className='truncate text-[11px] text-muted-foreground'>{scenario.instructions}</div>}
        <div className='text-[11px] text-muted-foreground'>{t('stepsCount', { count: scenario.steps.length })}</div>
      </div>

      <ScenarioDialog campaign={campaign} scenario={scenario}>
        <Button size='icon' variant='ghost' className='size-7 shrink-0' title={t('editTitle')}>
          <ChevronRight size={14} />
        </Button>
      </ScenarioDialog>

      <Button
        size='icon'
        variant='ghost'
        className='size-7 shrink-0 text-destructive hover:text-destructive'
        disabled={isPending}
        onClick={handleDelete}
        title={t('deleteTitle')}
      >
        <Trash2 size={12} />
      </Button>
    </div>
  );
}

