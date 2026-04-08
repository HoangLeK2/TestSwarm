'use client';

import { useState } from 'react';
import { Plus, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { useCreateScenario, useScenarios } from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { ScenarioRow } from './ScenarioRow';

export function ScenarioListDialog({ campaign, children }: { campaign: CampaignOut; children?: React.ReactNode }) {
  const t = useTranslations('campaignsFeature.scenarioList');
  const [open, setOpen] = useState(false);
  const { data: scenarios = [], refetch } = useScenarios(campaign.id);
  const { mutate: createScenario, isPending: isCreating } = useCreateScenario();

  const totalSteps = scenarios.reduce((sum, s) => sum + s.steps.length, 0);

  const handleAdd = () => {
    createScenario(
      {
        campaignId: campaign.id,
        data: { name: `Scenario ${scenarios.length + 1}`, order: scenarios.length }
      },
      {
        onSuccess: () => toast.success(t('createSuccess')),
        onError: () => toast.error(t('createFailed'))
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {children ?? (
          <Button variant='outline' size='sm' className='w-full justify-start gap-1.5 text-xs'>
            <FileText size={12} />
            {t('trigger', { scenarios: scenarios.length, steps: totalSteps })}
          </Button>
        )}
      </DialogTrigger>

      <DialogContent className='max-h-[80vh] overflow-y-auto sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('title', { campaign: campaign.name })}</DialogTitle>
        </DialogHeader>

        <div className='flex flex-col gap-2'>
          {scenarios.length === 0 ? (
            <p className='py-4 text-center text-sm text-muted-foreground'>{t('empty')}</p>
          ) : (
            scenarios.map((s) => (
              <ScenarioRow key={s.id} campaign={campaign} scenario={s} onDeleted={() => refetch()} />
            ))
          )}

          <Button
            variant='outline'
            size='sm'
            className='mt-1 gap-1.5'
            disabled={isCreating}
            onClick={handleAdd}
          >
            <Plus size={13} />
            {t('addButton')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

